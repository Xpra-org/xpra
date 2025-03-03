# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.log import Logger

log = Logger("command")


class ControlHandler:

    def __init__(self):
        self.control_commands: dict[str, Any] = {}

    def add_default_control_commands(self, enabled=True):
        # for things that can take longer:
        try:
            from xpra.net.control.common import HelloCommand, HelpCommand, DisabledCommand
            from xpra.net.control.debug import DebugControl
        except ImportError:
            return
        self.control_commands = {
            "hello": HelloCommand(),
        }
        if enabled:
            self.add_control_command("debug", DebugControl())
            self.add_control_command("help", HelpCommand(self.control_commands))
        else:
            self.add_control_command("*", DisabledCommand())

    def add_control_command(self, name: str, control) -> None:
        self.control_commands[name] = control

    def handle_command_request(self, proto, *args) -> None:
        """ client sent a command request as part of the hello packet """
        assert args, "no arguments supplied"
        from xpra.net.control.common import process_control_command
        code, response = process_control_command(proto, self.control_commands, *args)
        hello = {"command_response": (code, response)}
        proto.send_now(("hello", hello))
