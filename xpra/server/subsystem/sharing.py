# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

from typing import Any

from xpra.util.objects import typedict
from xpra.server.subsystem.stub import StubServerMixin
from xpra.net.common import Packet
from xpra.util.parsing import str_to_bool
from xpra.net.constants import ConnectionMessage
from xpra.log import Logger

log = Logger("server", "auth")


class SharingServer(StubServerMixin):
    """
    Adds management of sharing and locking of sessions
    """

    def __init__(self):
        StubServerMixin.__init__(self)
        self.sharing: bool | None = None
        self.lock: bool | None = None
        self.exit_with_client = False

    def init(self, opts) -> None:
        self.sharing = opts.sharing
        self.lock = opts.lock
        self.exit_with_client = opts.exit_with_client

    def setup(self) -> None:
        self.add_sharing_control_commands()

    def add_sharing_control_commands(self) -> None:
        ac = self.args_control
        ac("set-lock", "modify the lock attribute", min_args=1, max_args=1)
        ac("set-sharing", "modify the sharing attribute", min_args=1, max_args=1)

    def get_sharing_info(self) -> dict[str, Any]:
        return {
            "sharing": self.sharing is not False,
            "sharing-toggle": self.sharing is None,
            "lock": self.lock is not False,
            "lock-toggle": self.lock is None,
        }

    def get_info(self, _source=None) -> dict[str, Any]:
        return self.get_sharing_info()

    def get_server_features(self, _source) -> dict[str, Any]:
        return self.get_sharing_info()

    def parse_hello(self, source, c: typedict) -> str | ConnectionMessage:
        if not c.boolget("steal", True) and self._server_sources:
            return f"{ConnectionMessage.SESSION_BUSY}:this session is already active"

        # If we accept this connection, we may disconnect previous one(s)
        sharing = source.sharing
        uuid = source.uuid

        def drop_older_client() -> None:
            if uuid:
                for p, ss in tuple(self._server_sources.items()):
                    if ss != source and ss.uuid == uuid and not p.is_closed():
                        log("uuid %s is the same as %s", uuid, ss)
                        log("existing sources: %s", existing_sources)
                        self.disconnect_client(p, ConnectionMessage.NEW_CLIENT, "new connection from the same uuid")

        existing_sources = set(ss for ss in self._server_sources.values() if (ss != source and (uuid == "" or ss.uuid != uuid)))
        is_existing_client = uuid and any(ss.uuid == uuid for ss in existing_sources)

        log("checking sharing lock=%s, sharing=%s, existing sources=%s, is existing client=%s",
            self.lock, self.sharing, existing_sources, is_existing_client)
        if not existing_sources:
            log("no sharing conflicts: no other sources")
            drop_older_client()
            return ""

        # there are other clients connected,
        # figure out if we can share or take the session

        all_sharing = all((ss.share or not ss.requires_sharing()) for ss in existing_sources)
        if self.sharing is True or (self.sharing is None and sharing and all_sharing):
            log("sharing=%s, all_sharing=%s", self.sharing, all_sharing)
            drop_older_client()
            return ""

        locked = tuple(ss for ss in existing_sources if ss.lock)
        if self.lock is True or (self.lock is None and locked):
            log("session is locked (lock=%s, locked=%s", self.lock, locked)
            return f"{ConnectionMessage.SESSION_BUSY}:this session is locked"

        # sharing and lock checks have passed, so we will accept this client,
        # but we may need to disconnect other clients first,
        # start by dropping older connections from the same client:
        drop_older_client()
        share_count = 0
        disconnected = []
        req_sharing = source.requires_sharing()
        log("%s.requires_sharing()=%s", source, req_sharing)
        for p, ss in tuple(self._server_sources.items()):
            log("sharing, checking %s:", ss)
            if ss == source or uuid and ss.uuid == uuid:
                log("same source: %s", ss)
                continue
            if self.sharing is True:
                log("sharing all")
                share_count += 1
            elif self.sharing is False:
                log("not sharing, required by source %s: %s", source, req_sharing)
                if req_sharing:
                    self.disconnect_client(p, ConnectionMessage.NEW_CLIENT, "this session does not allow sharing")
                    disconnected.append(ss)
                else:
                    share_count += 1
            else:
                # `None` means "auto"
                assert self.sharing is None
                if ss.requires_sharing() and req_sharing and not source.sharing:
                    log("auto-sharing %s.sharing=%s, %s.sharing=%s", source, req_sharing, source, source.sharing)
                    self.disconnect_client(p, ConnectionMessage.NEW_CLIENT, "the new client does not wish to share")
                    disconnected.append(ss)
                elif not ss.share and req_sharing:
                    log("auto-sharing sharing required but not enabled for %s", ss)
                    self.disconnect_client(p, ConnectionMessage.NEW_CLIENT, "this client had not enabled sharing")
                    disconnected.append(ss)
                else:
                    log("auto-sharing for %s", ss)
                    share_count += 1

        # don't accept this connection if we're going to exit-with-client:
        if disconnected and self.exit_with_client:
            live = tuple(ss for ss in self._server_sources.values() if ss != source and ss not in disconnected)
            if not live:
                return f"{ConnectionMessage.SERVER_SHUTDOWN}:last client has exited"
        return ""

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
        if ss := self.get_server_source(proto):
            ss.lock = packet.get_bool(1)
            log("lock set to %s for client %i", ss.lock, ss.counter)

    def init_packet_handlers(self) -> None:
        # no need for main thread:
        self.add_packets("sharing-toggle", "lock-toggle")

    #########################################
    # Control Commands
    #########################################

    def control_command_set_lock(self, lock) -> str:
        self.lock = str_to_bool(lock)
        self.setting_changed("lock", lock is not False)
        self.setting_changed("lock-toggle", lock is None)
        return f"lock set to {self.lock}"

    def control_command_set_sharing(self, sharing) -> str:
        sharing = str_to_bool(sharing)
        message = f"sharing set to {self.sharing}"
        if sharing == self.sharing:
            return message
        self.sharing = sharing
        self.setting_changed("sharing", sharing is not False)
        self.setting_changed("sharing-toggle", sharing is None)
        if not sharing:
            # there can only be one ui client now,
            # disconnect all but the first ui_client:
            # (using the 'counter' value to figure out who was first connected)
            ui_clients = {
                getattr(ss, "counter", 0): proto
                for proto, ss in tuple(self._server_sources.items()) if getattr(ss, "ui_client", False)
            }
            n = len(ui_clients)
            if n > 1:
                for c in sorted(ui_clients)[1:]:
                    proto = ui_clients[c]
                    self.disconnect_client(proto, ConnectionMessage.SESSION_BUSY, "this session is no longer shared")
                message += f", disconnected {n - 1} clients"
        return message
