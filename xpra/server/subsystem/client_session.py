# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic
from typing import Any
from collections.abc import Sequence

from xpra.net.common import FULL_INFO
from xpra.net.constants import ConnectionMessage
from xpra.os_util import gi_import
from xpra.server.subsystem.stub import StubSubsystem
from xpra.util.background_worker import add_work_item
from xpra.util.objects import typedict, merge_dicts
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("server")
netlog = Logger("network")


class ClientSessionServer(StubSubsystem):
    """
    Owns accepted Xpra client sources and their UI-session lifecycle.
    """
    PREFIX = "client-session"

    def __init__(self, server=None):
        super().__init__(server)
        self.sources: dict = {}
        self.ui_driver = None

    def get_server_source(self, proto):
        return self.sources.get(proto)

    def get_sources_by_type(self, atype=object, exclude=None) -> Sequence:
        return tuple(
            ss for ss in self.sources.values()
            if isinstance(ss, atype) and (exclude is None or ss.uuid != exclude.uuid)
        )

    def is_authenticated(self, proto) -> bool:
        return proto in self.sources

    @staticmethod
    def get_client_connection_class(caps: typedict) -> type:
        from xpra.server.source.factory import get_client_connection_class
        return get_client_connection_class(caps)

    def hello_oked(self, proto, caps: typedict, auth_caps: dict) -> bool:
        if self.get_server_source(proto):
            log.warn("Warning: received another 'hello' packet")
            log.warn(" from an existing connection: %s", proto)
            return True
        if not self.server.sanity_checks(proto, caps):
            log("client failed sanity checks")
            return True

        def drop_client(reason="unknown", *args) -> None:
            self.server.disconnect_client(proto, reason, *args)

        cc_class = self.get_client_connection_class(caps)
        ss = cc_class(proto, drop_client, self.server, self.server.setting_changed)
        log("process_hello clientconnection=%s", ss)
        try:
            ss.parse_hello(caps)
        except Exception:
            ss.close()
            raise
        self.sources[proto] = ss
        self.server.accept_protocol(proto, caps)
        GLib.idle_add(self.process_hello_ui, ss, caps, auth_caps)
        return True

    def process_hello_ui(self, ss, caps: typedict, auth_caps: dict) -> None:
        def reject(*args) -> None:
            if proto := ss.protocol:
                self.server.disconnect_client(proto, *args)

        def closing() -> None:
            reject(ConnectionMessage.CONNECTION_ERROR, "server is shutting down")

        try:
            if self.server._closing:
                closing()
                return
            err = self.server.parse_hello(ss, caps)
            if err:
                reject(*err.split(":"))
                return
            self.server.send_hello(ss, auth_caps)
            log.info("Handshake complete; enabling connection")
            self.server.server_event("handshake-complete")
            self.server.notify_new_user(ss)
            self.server.add_new_client(ss, caps)
            self.server.send_initial_data(ss)
            self.server.client_startup_complete(ss)
            if self.server._closing:
                closing()
        except Exception:
            log("process_hello_ui%s", (ss, caps, auth_caps))
            log.error("Error: processing new connection from %s:", ss.protocol or ss, exc_info=True)
            reject("error accepting new connection")

    def dispatch_parse_hello(self, ss, caps: typedict) -> str | ConnectionMessage:
        return self.server._dispatch_first_truthy("parse_hello", ss, caps) or ""

    def dispatch_add_new_client(self, ss, caps: typedict) -> None:
        self.server._dispatch_fire("add_new_client", ss, caps)

    def dispatch_send_initial_data(self, ss) -> None:
        self.server._dispatch_fire("send_initial_data", ss)

    def client_startup_complete(self, ss) -> None:
        ss.startup_complete()
        self.server.server_event("startup-complete", ss.uuid)

    def cleanup_client_protocol(self, protocol):
        if source := self.sources.pop(protocol, None):
            self.server.cleanup_source(source)
            if ssh_agent := self.get_subsystem("ssh-agent"):
                # must stay after `cleanup_source` above: that emits `new-ui-driver`,
                # which also retargets the agent symlink - the last writer has to be this one
                ssh_agent.may_update_agent_symlinks(source)
            if mdns := self.get_subsystem("mdns"):
                add_work_item(mdns.mdns_update)
        return source

    def do_cleanup_source(self, source) -> None:
        ptype = "xpra"
        if FULL_INFO > 0:
            ptype = getattr(source, "client_type", "") or "xpra"
        self.server.server_event("connection-lost", source.uuid)
        self.server.emit("client-exited", source)
        remaining_sources = tuple(self.sources.values())
        if self.ui_driver == source.uuid:
            self.set_ui_driver(remaining_sources[0] if len(remaining_sources) == 1 else None)
        source.close()
        netlog("cleanup_source(%s) remaining sources: %s", source, remaining_sources)
        netlog.info("%s client %i disconnected.", ptype, source.counter)
        if not remaining_sources:
            GLib.idle_add(self.server.last_client_exited)

    def last_client_exited(self) -> None:
        sharing = self.get_subsystem("sharing")
        exit_with_client = bool(sharing and sharing.exit_with_client)
        netlog("last_client_exited() exit_with_client=%s", exit_with_client)
        self.server.emit("last-client-exited")
        if exit_with_client and not self.server._closing:
            netlog.info("Last client has disconnected, terminating")
            self.server.clean_quit(False)

    def sanity_checks(self, proto, caps: typedict) -> bool:
        server_uuid = caps.strget("server_uuid")
        if server_uuid:
            if server_uuid == self.server.subsystems["id"].uuid:
                self.server.send_disconnect(proto, "cannot connect a client running on the same display"
                                                   " that the server it connects to is managing - this would create a loop!")
                return False
            log.warn("Warning: this client is running nested")
            log.warn(f" in the Xpra server session {server_uuid!r}")
        return True

    def set_ui_driver(self, source) -> None:
        if source and self.ui_driver == source.uuid:
            return
        log("new ui driver: %s", source)
        self.ui_driver = source.uuid if source else None
        self.server.emit("new-ui-driver", source)

    def setting_changed(self, setting: str, value: Any) -> None:
        for ss in tuple(self.sources.values()):
            if setting == "readonly" and hasattr(ss, "server_enforced_readonly"):
                value = ss.server_enforced_readonly()
            ss.send_setting_change(setting, value)

    def _process_readonly_toggled(self, proto, packet) -> None:
        ss = self.get_server_source(proto)
        if not ss or not hasattr(ss, "set_client_readonly"):
            return
        ss.set_client_readonly(packet.get_bool(1))
        log("client %s toggled readonly=%s", ss, ss.client_readonly)

    def init_packet_handlers(self) -> None:
        self.add_packets("readonly-toggled")

    def disconnect_all(self) -> None:
        protocols = self.server.get_all_protocols()
        log("disconnect_all() all protocols=%s", protocols)
        for protocol in protocols:
            self.server.disconnect_client(protocol, ConnectionMessage.DETACH_REQUEST)

    def get_sources_info(self, proto, server_sources=()) -> dict[str, Any]:
        log("ClientSessionServer.get_sources_info%s", (proto, server_sources))
        start = monotonic()
        info: dict[str, Any] = {
            "clients": {
                "": sum(1 for p in self.sources if p != proto),
                "unauthenticated": sum(
                    1 for p in self.server._potential_protocols
                    if p is not proto and p not in self.sources
                ),
            },
        }
        log("unauthenticated protocols:")
        for i, p in enumerate(self.server._potential_protocols):
            log(f"{i:3} : {p}={p.get_info()}")
        cinfo = {}
        for i, ss in enumerate(server_sources):
            sinfo = ss.get_info()
            sinfo["ui-driver"] = self.ui_driver == ss.uuid
            cinfo[i] = sinfo
        merge_dicts(info, {"client": cinfo})
        log("ClientSessionServer.get_sources_info took %ims", (monotonic() - start) * 1000)
        return info
