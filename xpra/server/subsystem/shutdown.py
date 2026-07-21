# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.net.common import Packet, BACKWARDS_COMPATIBLE
from xpra.net.constants import ConnectionMessage
from xpra.net.packet_type import SHUTDOWN_SERVER, EXIT_SERVER
from xpra.server import ServerExitMode
from xpra.server.subsystem.stub import StubSubsystem
from xpra.util.env import envbool
from xpra.util.objects import typedict
from xpra.log import Logger

log = Logger("server")

CLIENT_CAN_SHUTDOWN = envbool("XPRA_CLIENT_CAN_SHUTDOWN", True)


class ShutdownServer(StubSubsystem):
    """
    Handles client requests that stop or exit a server.
    """
    __slots__ = ("client_shutdown",)
    PREFIX = "shutdown"
    toggle_features = ("client-shutdown",)

    def __init__(self, server=None):
        super().__init__(server)
        self.client_shutdown: bool = CLIENT_CAN_SHUTDOWN
        self.server.hello_request_handlers.update({
            "exit": self._handle_hello_request_exit,
            "stop": self._handle_hello_request_stop,
        })

    def get_server_features(self, _source=None) -> dict[str, Any]:
        return {
            "client-shutdown": self.client_shutdown,
        }

    def _process_exit_server(self, _proto, packet: Packet = Packet(EXIT_SERVER)) -> None:
        assert BACKWARDS_COMPATIBLE
        reason = packet.get_str(1) if len(packet) > 1 else ""
        self._request_exit(reason)

    def _handle_hello_request_exit(self, _proto, _caps: typedict) -> bool:
        self._request_exit()
        return True

    def _request_exit(self, reason: ConnectionMessage | str = "") -> None:
        message = "Exiting in response to client request"
        if reason:
            message += f": {reason}"
        log.info(message)
        self.server.cleanup_all_protocols(reason=reason)
        self.timeout_add(500, self.server.clean_quit, ServerExitMode.EXIT)

    def _process_shutdown_server(self, _proto, packet: Packet = Packet(SHUTDOWN_SERVER)) -> None:
        # an optional boolean argument requests a full server exit rather than a shutdown,
        # (older clients send a separate `exit-server` packet, see `_process_exit_server`)
        # the exit mode defaults to `False` (shutdown) and the reason to the empty string:
        exit_server = packet.get_bool(1) if len(packet) > 1 else False
        if exit_server:
            reason = packet.get_str(2) if len(packet) > 2 else ""
            self._request_exit(reason)
        else:
            self._request_stop()

    def _handle_hello_request_stop(self, _proto, _caps: typedict) -> bool:
        return self._request_stop()

    def _request_stop(self) -> bool:
        if not self.client_shutdown:
            log.warn("Warning: ignoring shutdown request")
            return False
        log.info("Shutting down in response to client request")
        self.server.cleanup_all_protocols(reason=ConnectionMessage.SERVER_SHUTDOWN)
        self.timeout_add(500, self.server.clean_quit)
        return True

    def init_packet_handlers(self) -> None:
        self.add_packets(SHUTDOWN_SERVER)
        if BACKWARDS_COMPATIBLE:
            self.add_packets(EXIT_SERVER)
