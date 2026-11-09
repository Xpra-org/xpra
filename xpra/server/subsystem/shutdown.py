# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.net.common import Packet
from xpra.net.constants import ConnectionMessage
from xpra.net.packet_type import SHUTDOWN_SERVER
from xpra.server import ServerExitMode
from xpra.server.subsystem.stub import StubSubsystem
from xpra.util.objects import typedict
from xpra.log import Logger

log = Logger("server")


class ShutdownServer(StubSubsystem):
    """
    Handles client requests that stop or exit a server.
    """
    __slots__ = ("client_shutdown",)
    PREFIX = "shutdown"
    toggle_features = ("client-shutdown",)

    def __init__(self, server=None):
        super().__init__(server)
        self.client_shutdown: bool = True
        self.server.hello_request_handlers.update({
            "exit": self._handle_hello_request_exit,
            "stop": self._handle_hello_request_stop,
        })

    def init(self, opts) -> None:
        self.client_shutdown = opts.client_shutdown

    def get_server_features(self, _source=None) -> dict[str, Any]:
        return {
            "client-shutdown": self.client_shutdown,
        }

    def _handle_hello_request_exit(self, _proto, _caps: typedict) -> bool:
        return self._request_exit()

    def _request_exit(self, reason: ConnectionMessage | str = "") -> bool:
        if not self.client_shutdown:
            log.warn("Warning: ignoring exit request, client shutdown is disabled")
            return False
        message = "Exiting in response to client request"
        if reason:
            message += f": {reason}"
        log.info(message)
        self.network.cleanup_all_protocols(reason=reason)
        self.timeout_add(500, self.server.clean_quit, ServerExitMode.EXIT)
        return True

    def _process_server(self, proto, packet: Packet = Packet(SHUTDOWN_SERVER)) -> None:
        # an optional boolean argument requests a full server exit rather than a shutdown,
        # the exit mode defaults to `False` (shutdown) and the reason to the empty string:
        exit_server = packet.get_bool(1) if len(packet) > 1 else False
        if self.is_readonly(proto):
            log.warn("Warning: %s request denied by readonly mode", "exit" if exit_server else "shutdown")
            return
        if exit_server:
            reason = packet.get_str(2) if len(packet) > 2 else ""
            self._request_exit(reason)
        else:
            self._request_stop()

    def _handle_hello_request_stop(self, _proto, _caps: typedict) -> bool:
        return self._request_stop()

    def _request_stop(self) -> bool:
        if not self.client_shutdown:
            log.warn("Warning: ignoring shutdown request, client shutdown is disabled")
            return False
        log.info("Shutting down in response to client request")
        self.network.cleanup_all_protocols(reason=ConnectionMessage.SERVER_SHUTDOWN)
        self.timeout_add(500, self.server.clean_quit)
        return True

    def init_packet_handlers(self) -> None:
        self.add_packets(SHUTDOWN_SERVER)
