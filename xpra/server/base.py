# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from time import monotonic
from typing import Any

from xpra.server.core import ServerCore
from xpra.util.background_worker import add_work_item
from xpra.common import FULL_INFO, noop, subsystem_name, ConnectionMessage, BACKWARDS_COMPATIBLE
from xpra.net.common import Packet, PacketElement
from xpra.os_util import WIN32, gi_import
from xpra.platform.dotxpra import DotXpra
from xpra.util.objects import typedict, merge_dicts
from xpra.util.str_fn import csv, Ellipsizer
from xpra.util.env import envbool
from xpra.net.bytestreams import set_socket_timeout
from xpra.server import features, ServerExitMode
from xpra.server.factory import get_server_base_classes
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("server")
netlog = Logger("network")
authlog = Logger("auth")

SERVER_BASES = get_server_base_classes()
SIGNALS: dict[str, tuple] = {}
for base_class in SERVER_BASES:
    SIGNALS.update(getattr(base_class, "__signals__", {}))
ServerBaseClass = type("ServerBaseClass", SERVER_BASES, {})
log("ServerBaseClass%s", SERVER_BASES)
log("signals: %s", SIGNALS)

CLIENT_CAN_SHUTDOWN = envbool("XPRA_CLIENT_CAN_SHUTDOWN", True)
MDNS_CLIENT_COUNT = envbool("XPRA_MDNS_CLIENT_COUNT", True)


class ServerBase(ServerBaseClass):
    """
    This is the base class for seamless and desktop servers. (not proxy servers)
    It provides all the generic functions but is not tied
    to a specific backend (X11 or otherwise).
    See X11ServerBase and other platform specific subclasses.
    """
    __signals__ = SIGNALS

    def __init__(self):
        for c in SERVER_BASES:
            c.__init__(self)
        log("ServerBase.__init__()")
        self.hello_request_handlers.update({
            "detach": self._handle_hello_request_detach,
            "exit": self._handle_hello_request_exit,
            "stop": self._handle_hello_request_stop,
        })
        self._server_sources: dict = {}
        self.client_properties: dict[int, dict] = {}
        self.ui_driver = None
        self.sharing: bool | None = None
        self.lock: bool | None = None
        self.idle_timeout: int = 0
        self.client_shutdown: bool = CLIENT_CAN_SHUTDOWN
        self.dotxpra = None

    def suspend_event(self, *_args) -> None:
        # if we get a `suspend_event`, we can assume that `PowerEventServer` is a superclass:
        self.server_event("suspend")
        for s in self._server_sources.values():
            if hasattr(s, "go_idle"):
                s.go_idle()

    def resume_event(self, *_args) -> None:
        self.server_event("resume")
        for s in self._server_sources.values():
            if hasattr(s, "no_idle"):
                s.no_idle()

    def server_event(self, event_type: str, *args: PacketElement) -> None:
        for s in self._server_sources.values():
            s.send_server_event(event_type, *args)
        # the bus mixin is optional:
        dbus_server = getattr(self, "dbus_server", None)
        if dbus_server:
            dbus_server.Event(event_type, [str(x) for x in args[1:]])

    def get_server_source(self, proto):
        return self._server_sources.get(proto)

    def init(self, opts) -> None:
        self.dotxpra = DotXpra(opts.socket_dir, opts.socket_dirs + opts.client_socket_dirs)
        # from now on, use the logger for parsing errors:
        from xpra.scripts import config  # pylint: disable=import-outside-toplevel
        config.warn = log.warn
        for c in SERVER_BASES:
            start = monotonic()
            c.init(self, opts)
            end = monotonic()
            log("%3ims in %s.init", 1000 * (end - start), c)
        self.sharing = opts.sharing
        self.lock = opts.lock
        self.idle_timeout = opts.idle_timeout

    def setup(self) -> None:
        log("starting component init")
        for c in SERVER_BASES:
            start = monotonic()
            c.setup(self)
            end = monotonic()
            log("%3ims in %s.setup", 1000 * (end - start), c)

    def threaded_setup(self) -> None:
        log("threaded_init() serverbase start")
        for c in SERVER_BASES:
            with log.trap_error("Error during threaded setup of %s", c):
                c.threaded_setup(self)
        log("threaded_init() serverbase end")

    def server_is_ready(self) -> None:
        super().server_is_ready()
        self.server_event("ready")

    def do_cleanup(self) -> None:
        self.server_event("exit")
        self.wait_for_threaded_init()
        log("do_cleanup() calling on %s", SERVER_BASES)
        for c in reversed(SERVER_BASES):
            if c != ServerCore:
                log("%s", c.cleanup)
                try:
                    c.cleanup(self)
                except Exception:
                    log.warn(f"Error: in {c} cleanup", exc_info=True)

    def late_cleanup(self, stop=True) -> None:
        for c in reversed(SERVER_BASES):
            log("%s", c.late_cleanup)
            c.late_cleanup(self, stop)

    ######################################################################
    # override http scripts to expose just the current session / display
    def get_displays(self) -> dict[str, Any]:
        from xpra.scripts.main import get_displays  # pylint: disable=import-outside-toplevel
        return get_displays(self.dotxpra, display_names=(os.environ.get("DISPLAY"),))

    def get_xpra_sessions(self) -> dict[str, Any]:
        from xpra.scripts.main import get_xpra_sessions  # pylint: disable=import-outside-toplevel
        return get_xpra_sessions(self.dotxpra, matching_display=os.environ.get("DISPLAY"))

    ######################################################################
    # shutdown / exit commands:
    def _process_exit_server(self, _proto, packet: Packet = Packet("exit-server")) -> None:
        # packet from a client
        reason = ""
        if len(packet) > 1:
            reason = packet.get_str(1)
        self._request_exit(reason)

    def _handle_hello_request_exit(self, _proto, _caps: typedict) -> bool:
        # handle "xpra exit" hello request
        self._request_exit()
        return True

    def _request_exit(self, reason: ConnectionMessage | str = "") -> None:
        message = "Exiting in response to client request"
        if reason:
            message += f": {reason}"
        log.info(message)
        self.cleanup_all_protocols(reason=reason)
        GLib.timeout_add(500, self.clean_quit, ServerExitMode.EXIT)

    def _process_shutdown_server(self, _proto, _packet: Packet = Packet("shutdown-server")) -> None:
        self._request_stop()

    def _handle_hello_request_stop(self, _proto, _caps: typedict) -> bool:
        return self._request_stop()

    def _request_stop(self) -> bool:
        if not self.client_shutdown:
            log.warn("Warning: ignoring shutdown request")
            return False
        log.info("Shutting down in response to client request")
        self.cleanup_all_protocols(reason=ConnectionMessage.SERVER_SHUTDOWN)
        GLib.timeout_add(500, self.clean_quit)
        return True

    def get_mdns_info(self) -> dict[str, Any]:
        mdns_info = ServerCore.get_mdns_info(self)
        if MDNS_CLIENT_COUNT:
            mdns_info["clients"] = len(self._server_sources)
        return mdns_info

    ######################################################################
    # handle new connections:
    # noinspection PySimplifyBooleanCheck
    def handle_sharing(self, proto, ui_client: bool = True, share: bool = False,
                       uuid="") -> tuple[bool, int]:
        share_count = 0
        disconnected = 0
        existing_sources = set(ss for p, ss in self._server_sources.items() if p != proto)
        is_existing_client = uuid and any(ss.uuid == uuid for ss in existing_sources)
        authlog("handle_sharing%s lock=%s, sharing=%s, existing sources=%s, is existing client=%s",
                (proto, ui_client, share, uuid),
                self.lock, self.sharing, existing_sources, is_existing_client)
        # if other clients are connected, verify we can steal or share:
        if existing_sources and not is_existing_client:
            if self.sharing is True or (self.sharing is None and share and all(ss.share for ss in existing_sources)):
                authlog("handle_sharing: sharing with %s", tuple(existing_sources))
            elif self.lock is True:
                authlog("handle_sharing: session is locked")
                self.disconnect_client(proto, ConnectionMessage.SESSION_BUSY, "this session is locked")
                return False, 0
            elif self.lock is not False and any(ss.lock for ss in existing_sources):
                authlog("handle_sharing: another client has locked the session: " + csv(
                    ss for ss in existing_sources if ss.lock))
                self.disconnect_client(proto, ConnectionMessage.SESSION_BUSY, "a client has locked this session")
                return False, 0
        # we're either sharing, or the only client:
        for p, ss in tuple(self._server_sources.items()):
            if uuid and ss.uuid == uuid and ui_client and ss.ui_client:
                authlog("uuid %s is the same as %s", uuid, ss)
                authlog("existing sources: %s", existing_sources)
                self.disconnect_client(p, ConnectionMessage.NEW_CLIENT, "new connection from the same uuid")
                disconnected += 1
            elif ui_client and ss.ui_client:
                # check if existing sessions are willing to share:
                if self.sharing is True:
                    share_count += 1
                elif self.sharing is False:
                    self.disconnect_client(p, ConnectionMessage.NEW_CLIENT, "this session does not allow sharing")
                    disconnected += 1
                else:
                    assert self.sharing is None
                    if not share:
                        self.disconnect_client(p, ConnectionMessage.NEW_CLIENT, "the new client does not wish to share")
                        disconnected += 1
                    elif not ss.share:
                        self.disconnect_client(p, ConnectionMessage.NEW_CLIENT, "this client had not enabled sharing")
                        disconnected += 1
                    else:
                        share_count += 1

        # don't accept this connection if we're going to exit-with-client:
        accepted = True
        if disconnected > 0 and share_count == 0 and self.exit_with_client:
            self.disconnect_client(proto, ConnectionMessage.SERVER_SHUTDOWN, "last client has exited")
            accepted = False
        return accepted, share_count

    def hello_oked(self, proto, c: typedict, auth_caps: dict) -> None:
        if self._server_sources.get(proto):
            log.warn("Warning: received another 'hello' packet")
            log.warn(" from an existing connection: %s", proto)
            return
        if super().hello_oked(proto, c, auth_caps):
            # has been handled
            return
        if not self.sanity_checks(proto, c):
            return
        if not c.boolget("steal", True) and self._server_sources:
            self.disconnect_client(proto, ConnectionMessage.SESSION_BUSY, "this session is already active")
            return
        log.info("Handshake complete; enabling connection")
        self.server_event("handshake-complete")

        # Things are okay, we accept this connection, and may disconnect previous one(s)
        # (but only if this is going to be a UI session - control sessions can co-exist)
        ui_client = c.boolget("ui_client", True)
        share = c.boolget("share")
        uuid = c.strget("uuid")
        accepted, share_count = self.handle_sharing(proto, ui_client, share, uuid)
        if not accepted:
            return

        self.accept_client(proto, c)
        # use blocking sockets from now on:
        if not WIN32:
            set_socket_timeout(proto._conn, None)

        def drop_client(reason="unknown", *args) -> None:
            self.disconnect_client(proto, reason, *args)

        cc_class = self.get_client_connection_class(c)
        ss = cc_class(proto, drop_client, self, self.setting_changed)
        log("process_hello clientconnection=%s", ss)
        try:
            ss.parse_hello(c)
        except Exception:
            # close it already
            ss.close()
            raise
        self._server_sources[proto] = ss
        # process ui half in ui thread:
        GLib.idle_add(self.process_hello_ui, ss, c, auth_caps, ui_client, share_count)

    def _handle_hello_request_detach(self, proto, _caps: typedict) -> bool:
        # noinspection PySimplifyBooleanCheck
        if self.lock is True:
            authlog("cannot detach: session is locked")
            self.disconnect_client(proto, ConnectionMessage.SESSION_BUSY, "this session is locked")
            return False
        count = locked = 0
        for p, ss in tuple(self._server_sources.items()):
            if p != proto:
                if ss.lock:
                    locked += 1
                else:
                    authlog("handle_sharing: detaching %s", ss)
                    self.disconnect_client(p, ConnectionMessage.DETACH_REQUEST)
                    count += 1
        message = f"{count} clients have been disconnected"
        if locked:
            message += f", {locked} still have it locked"
        self.disconnect_client(proto, ConnectionMessage.DONE, message)
        return True

    @staticmethod
    def get_client_connection_class(caps: typedict) -> type:
        # pylint: disable=import-outside-toplevel
        from xpra.server.source.factory import get_client_connection_class
        return get_client_connection_class(caps)

    def process_hello_ui(self, ss, c: typedict, auth_caps: dict, send_ui: bool, share_count: int) -> None:
        def reject(message="server is shutting down") -> None:
            p = ss.protocol
            if p:
                self.disconnect_client(p, ConnectionMessage.CONNECTION_ERROR, message)

        # adds try:except around parse hello ui code:
        try:
            if self._closing:
                reject()
                return

            self.notify_new_user(ss)

            self.parse_hello(ss, c, send_ui)
            # send_hello will take care of sending the current and max screen resolutions

            self.send_hello(ss, auth_caps)
            self.add_new_client(ss, c, send_ui, share_count)
            self.update_all_server_settings(share_count == 0)  # if we're not sharing, reset all the settings
            self.send_initial_data(ss, c, send_ui, share_count)
            self.client_startup_complete(ss)

            if self._closing:
                reject()
                return
        except Exception:
            # log exception but don't disclose internal details to the client
            log("process_hello_ui%s", (ss, c, auth_caps, send_ui, share_count))
            log.error("Error: processing new connection from %s:", ss.protocol or ss, exc_info=True)
            reject("error accepting new connection")

    def parse_hello(self, ss, c: typedict, send_ui: bool) -> None:
        for bc in SERVER_BASES:
            if bc != ServerCore:
                bc.parse_hello(self, ss, c, send_ui)

    def add_new_client(self, ss, c: typedict, send_ui: bool, share_count: int) -> None:
        for bc in SERVER_BASES:
            if bc != ServerCore:
                bc.add_new_client(self, ss, c, send_ui, share_count)

    def send_initial_data(self, ss, c: typedict, send_ui: bool, share_count: int) -> None:
        for bc in SERVER_BASES:
            if bc != ServerCore:
                bc.send_initial_data(self, ss, c, send_ui, share_count)

    def client_startup_complete(self, ss) -> None:
        ss.startup_complete()
        self.server_event("startup-complete", ss.uuid)

    def sanity_checks(self, proto, c: typedict) -> bool:
        server_uuid = c.strget("server_uuid")
        if server_uuid:
            if server_uuid == self.uuid:
                self.send_disconnect(proto, "cannot connect a client running on the same display"
                                            " that the server it connects to is managing - this would create a loop!")
                return False
            log.warn("Warning: this client is running nested")
            log.warn(f" in the Xpra server session {server_uuid!r}")
        return True

    def update_all_server_settings(self, reset: bool = False) -> None:
        pass  # may be overridden in subclasses (ie: x11 server)

    ######################################################################
    # hello:
    def get_server_features(self, server_source=None) -> dict[str, Any]:
        # these are flags that have been added over time with new versions
        # to expose new server features:
        f: dict[str, Any] = {}
        for c in SERVER_BASES:
            if c != ServerCore:
                bf = c.get_server_features(self, server_source)
                log(f"get_server_features({c})={bf}")
                merge_dicts(f, bf)
        return f

    def make_hello(self, source) -> dict[str, Any]:
        capabilities = super().make_hello(source)
        for c in SERVER_BASES:
            if c != ServerCore:
                caps = c.get_caps(self, source)
                log("%s.get_caps(%s)=%s", c, source, caps)
                merge_dicts(capabilities, caps)
        capabilities["server_type"] = "base"
        if "features" in source.wants:
            capabilities |= {
                "client-shutdown": self.client_shutdown,
                "sharing": self.sharing is not False,
                "sharing-toggle": self.sharing is None,
                "lock": self.lock is not False,
                "lock-toggle": self.lock is None,
                "windows": features.window,
                "keyboard": features.keyboard,
            }
            sf = self.get_server_features(source)
            capabilities.update(sf)
        return capabilities

    def send_hello(self, server_source, server_cipher: dict) -> None:
        capabilities = self.make_hello(server_source)
        if server_cipher:
            capabilities.update(server_cipher)
        server_source.send_hello(capabilities)

    ######################################################################
    # utility method:
    def window_sources(self) -> tuple:
        from xpra.server.source.window import WindowsConnection  # pylint: disable=import-outside-toplevel
        return tuple(x for x in self._server_sources.values() if isinstance(x, WindowsConnection))

    ######################################################################
    # info:
    def send_hello_info(self, proto, **kwargs) -> None:
        self.wait_for_threaded_init()
        super().send_hello_info(proto, **kwargs)

    def get_ui_info(self, proto, **kwargs) -> dict[str, Any]:
        """ info that must be collected from the UI thread
            (ie: things that query the display)
        """
        info: dict[str, Any] = {}
        subsystems = kwargs.get("subsystems", ())
        log("ServerBase.get_ui_info(%s, %s) subsystems=%s", proto, kwargs, subsystems)
        for c in SERVER_BASES:
            if subsystems and subsystem_name(c) not in subsystems:
                continue
            with log.trap_error("Error collecting UI info from %s", c):
                mixin_info = c.get_ui_info(self, proto, **kwargs)
                log("%s.get_ui_info(%s, ..)=%r", c, proto, Ellipsizer(mixin_info))
                merge_dicts(info, mixin_info)
        return info

    def get_threaded_info(self, proto, **kwargs) -> dict[str, Any]:
        log("ServerBase.get_threaded_info%s", (proto, kwargs))
        start = monotonic()
        info: dict[str, Any] = {}
        subsystems = kwargs.get("subsystems", ())

        def up(prefix, d) -> None:
            merge_dicts(info, {prefix: d})

        for c in SERVER_BASES:
            if subsystems and subsystem_name(c) not in subsystems:
                continue
            with log.trap_error(f"Error collecting information from {c}"):
                cstart = monotonic()
                mixin_info = c.get_info(self, proto)
                log("%s.get_info(%s)=%r", c, proto, Ellipsizer(mixin_info))
                merge_dicts(info, mixin_info)
                cend = monotonic()
                log("%s.get_info(%s) took %ims", c, proto, int(1000 * (cend - cstart)))

        if not subsystems or "features" in subsystems:
            up("features", self.get_features_info())
        if not subsystems or "network" in subsystems:
            up("network", {
                "sharing": self.sharing is not False,
                "sharing-toggle": self.sharing is None,
                "lock": self.lock is not False,
                "lock-toggle": self.lock is None,
            })
        info["subsystems"] = self.get_subsystems()

        sources = tuple(self._server_sources.values())
        client_uuids = kwargs.get("client_uuids", ())
        if client_uuids:
            sources = tuple(ss for ss in sources if ss.uuid in client_uuids)
        log("threaded info sources(%i)=%s", client_uuids, sources)
        info.update(self.get_sources_info(proto, sources))
        log("ServerBase.get_info took %.1fms", 1000.0 * (monotonic() - start))
        return info

    def get_features_info(self) -> dict[str, Any]:
        i = {
            "sharing": self.sharing is not False,
            "idle_timeout": self.idle_timeout,
        }
        i.update(self.get_server_features())
        return i

    def get_subsystems(self) -> list[str]:
        return super().get_subsystems() + [subsystem_name(c) for c in SERVER_BASES]

    def get_sources_info(self, proto, server_sources=()) -> dict[str, Any]:
        log("ServerBase.get_source_info%s", (proto, server_sources))
        start = monotonic()
        info: dict[str, Any] = {}

        def up(prefix, d) -> None:
            merge_dicts(info, {prefix: d})

        info["clients"] = {
            "": sum(1 for p in self._server_sources if p != proto),
            "unauthenticated": sum(1 for p in self._potential_protocols
                                   if ((p is not proto) and (p not in self._server_sources))),
        }
        log("unauthenticated protocols:")
        for i, p in enumerate(self._potential_protocols):
            log(f"{i:3} : {p}={p.get_info()}")
        # find the server source to report on:
        n = len(server_sources)
        if n == 1:
            ss = server_sources[0]
            up("client", ss.get_info())
        elif n > 1:
            cinfo = {}
            for i, ss in enumerate(server_sources):
                sinfo = ss.get_info()
                sinfo["ui-driver"] = self.ui_driver == ss.uuid
                cinfo[i] = sinfo
            up("client", cinfo)
        log("ServerBase.get_source_info took %ims", (monotonic() - start) * 1000)
        return info

    def _process_server_settings(self, proto, packet: Packet) -> None:
        # only used by x11 servers
        pass

    def _set_client_properties(self, proto, wid: int, window, new_client_properties: dict) -> None:
        """
        Allows us to keep window properties for a client after disconnection.
        (we keep it in a map with the client's uuid as key)
        """
        ss = self.get_server_source(proto)
        if ss:
            ss.set_client_properties(wid, window, typedict(new_client_properties))
            # filter out encoding properties, which are expected to be set every time:
            ncp = {}
            for k, v in new_client_properties.items():
                if v is None:
                    log.warn("removing invalid None property for %s", k)
                    continue
                k = str(k)
                if k == "event":
                    # event is used as a workaround in _process_map_window,
                    # it isn't a real client property and should not be stored:
                    continue
                if not k.startswith("encoding"):
                    ncp[k] = v
            if ncp:
                log("set_client_properties updating window %#x of source %s with %s", wid, ss.uuid, ncp)
                client_properties = self.client_properties.setdefault(wid, {}).setdefault(ss.uuid, {})
                client_properties.update(ncp)

    ######################################################################
    # settings toggle:
    def setting_changed(self, setting: str, value: Any) -> None:
        # tell all the clients (that can) about the new value for this setting
        for ss in tuple(self._server_sources.values()):
            ss.send_setting_change(setting, value)

    def _process_sharing_toggle(self, proto, packet: Packet) -> None:
        assert self.sharing is None
        ss = self.get_server_source(proto)
        if not ss:
            return
        sharing = packet.get_bool(1)
        ss.share = sharing
        if not sharing:
            # disconnect other users:
            for p, ss in tuple(self._server_sources.items()):
                if p != proto:
                    self.disconnect_client(p, ConnectionMessage.DETACH_REQUEST,
                                           f"client {ss.counter} no longer wishes to share the session")

    def _process_lock_toggle(self, proto, packet: Packet) -> None:
        assert self.lock is None
        ss = self.get_server_source(proto)
        if ss:
            ss.lock = packet.get_bool(1)
            log("lock set to %s for client %i", ss.lock, ss.counter)

    ######################################################################
    # add clients to http server info:
    def get_http_info(self) -> dict[str, Any]:
        info = super().get_http_info()
        info["clients"] = len(self._server_sources)
        return info

    ######################################################################
    # client connections:
    def init_sockets(self, sockets) -> None:
        for c in SERVER_BASES:
            c.init_sockets(self, sockets)

    def cleanup_protocol(self, protocol):
        netlog("cleanup_protocol(%s)", protocol)
        # this ensures that from now on we ignore any incoming packets coming
        # from this connection as these could potentially set some keys pressed, etc
        try:
            self._potential_protocols.remove(protocol)
        except ValueError:
            pass
        source = self._server_sources.pop(protocol, None)
        if source:
            self.cleanup_source(source)
            mdns_update = getattr(self, "mdns_update", noop)
            add_work_item(mdns_update)
        for c in SERVER_BASES:
            c.cleanup_protocol(self, protocol)
        return source

    def cleanup_source(self, source) -> None:
        ptype = "xpra"
        if FULL_INFO > 0:
            ptype = getattr(source, "client_type", "") or "xpra"
        self.server_event("connection-lost", source.uuid)
        for bc in SERVER_BASES:
            with log.trap_error("Error removing client %s from %s", source, bc):
                bc.remove_client(self, source)

        remaining_sources = tuple(self._server_sources.values())
        if self.ui_driver == source.uuid:
            if len(remaining_sources) == 1:
                self.set_ui_driver(remaining_sources[0])
            else:
                self.set_ui_driver(None)
        source.close()
        netlog("cleanup_source(%s) remaining sources: %s", source, remaining_sources)
        netlog.info("%s client %i disconnected.", ptype, source.counter)
        has_client = len(remaining_sources) > 0
        if not has_client:
            GLib.idle_add(self.last_client_exited)

    def last_client_exited(self) -> None:
        # must run from the UI thread (modifies focus and keys)
        netlog("last_client_exited() exit_with_client=%s", self.exit_with_client)
        for c in SERVER_BASES:
            if c != ServerCore:
                try:
                    c.last_client_exited(self)
                except Exception:
                    log("last_client_exited calling %s", c.last_client_exited, exc_info=True)
        if self.exit_with_client and not self._closing:
            netlog.info("Last client has disconnected, terminating")
            self.clean_quit(False)

    def set_ui_driver(self, source) -> None:
        if source and self.ui_driver == source.uuid:
            return
        log("new ui driver: %s", source)
        if not source:
            self.ui_driver = None
        else:
            self.ui_driver = source.uuid
        for c in SERVER_BASES:
            if c != ServerCore:
                c.set_session_driver(self, source)

    def get_all_protocols(self) -> list:
        return list(self._potential_protocols) + list(self._server_sources.keys())

    def is_timedout(self, protocol) -> bool:
        v = super().is_timedout(protocol) and protocol not in self._server_sources
        netlog("is_timedout(%s)=%s", protocol, v)
        return v

    def _disconnect_proto_info(self, proto) -> str:
        # only log protocol info if there is more than one client:
        if len(self._server_sources) > 1:
            return " %s" % proto
        return ""

    def init_packet_handlers(self) -> None:
        for c in SERVER_BASES:
            c.init_packet_handlers(self)
        # no need for main thread:
        self.add_packets("sharing-toggle", "lock-toggle")
        self.add_packet_handler("set_deflate", noop)  # removed in v6
        if BACKWARDS_COMPATIBLE:
            # now moved to XSettingsServer
            self.add_packets("server-settings", main_thread=True)
        self.add_packets("shutdown-server", "exit-server")

    # override so we can set the 'authenticated' flag:
    def process_packet(self, proto, packet: Packet) -> None:
        authenticated = bool(self.get_server_source(proto))
        return super().dispatch_packet(proto, packet, authenticated)

    def handle_invalid_packet(self, proto, packet: Packet) -> None:
        ss = self.get_server_source(proto)
        if not self._closing and not proto.is_closed() and (ss is None or not ss.is_closed()):
            netlog("invalid packet: %s", packet)
            packet_type = packet.get_type()
            netlog.error(f"Error: unknown or invalid packet type {packet_type!r}")
            netlog.error(f" received from {proto}")
        if not ss:
            proto.close()
