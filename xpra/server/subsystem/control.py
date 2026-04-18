# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.net.common import Packet
from xpra.net.control.common import ControlCode
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger

log = Logger("command")


class ControlHandler(StubServerMixin):

    def __init__(self):
        StubServerMixin.__init__(self)
        self.control_commands: dict[str, Any] = {}
        self.control_enabled = False

    def init(self, opts) -> None:
        self.control_enabled = opts.control

    def setup(self) -> None:
        self.add_default_control_commands()

    def add_default_control_commands(self) -> None:
        # for things that can take longer:
        try:
            from xpra.net.control.common import HelloCommand, HelpCommand, DisabledCommand
        except ImportError:
            return
        self.control_commands = {
            "hello": HelloCommand(),
        }
        if self.control_enabled:
            self.do_add_control_command("help", HelpCommand(self.control_commands))
        else:
            self.do_add_control_command("*", DisabledCommand())

    def add_control_command(self, name: str, control) -> None:
        if self.control_enabled:
            self.do_add_control_command(name, control)

    def do_add_control_command(self, name: str, control) -> None:
        self.control_commands[name] = control

    def process_control_command(self, proto, *args) -> tuple[ControlCode | int, str]:
        from xpra.net.control.common import process_control_command
        return process_control_command(proto, self.control_commands, *args)

    def handle_command_request(self, proto, *args) -> None:
        """ client sent a command request as part of the hello packet """
        if not args:
            raise ValueError("no arguments supplied")
        from xpra.net.control.common import process_control_command
        code, response = process_control_command(proto, self.control_commands, *args)
        hello = {"command_response": (int(code), response)}
        proto.send_now(Packet("hello", hello))
