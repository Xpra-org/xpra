# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.client.base.stub import StubClientMixin
from xpra.net.common import Packet
from xpra.util.objects import typedict
from xpra.log import Logger

log = Logger("exec")


class ControlClient(StubClientMixin):
    """
    Utility mixin for clients that support a control channel

    the actual dispatching of "control" requests is done in `UIXpraClient` for server connections
    """
    PREFIX = "control"

    def __init__(self):
        self.control_commands: dict[str, Any] = {}

    def get_info(self) -> dict[str, tuple]:
        return {
            "control": tuple(self.control_commands.keys())
        }

    def parse_server_capabilities(self, c: typedict) -> bool:
        self.add_control_commands()
        return True

    def add_control_commands(self) -> None:
        try:
            from xpra.net.control.common import HelloCommand, HelpCommand, DisabledCommand
            from xpra.net.control.debug import DebugControl
        except ImportError:
            return
        self.control_commands |= {
            "hello": HelloCommand(),
            "debug": DebugControl(),
            "help": HelpCommand(self.control_commands),
            "*": DisabledCommand(),
        }

    def add_control_command(self, name: str, control) -> None:
        self.control_commands[name] = control

    def _process_control(self, packet: Packet) -> None:
        args = packet[1:]
        code, msg = self.process_control_command(self._protocol, *args)
        log.warn(f"{code}, {msg!r}")

    def process_control_command(self, proto, *args) -> tuple[int, str]:
        from xpra.net.control.common import process_control_command
        return process_control_command(proto, self.control_commands, *args)

    def init_authenticated_packet_handlers(self) -> None:
        self.add_packets("control", main_thread=True)
