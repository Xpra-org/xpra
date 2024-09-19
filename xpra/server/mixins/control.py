# This file is part of Xpra.
# Copyright (C) 2010-2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.util.str_fn import csv
from xpra.scripts.config import str_to_bool
from xpra.server.mixins.stub_server_mixin import StubServerMixin
from xpra.log import Logger

log = Logger("command")


class ControlHandler(StubServerMixin):

    def __init__(self):
        self.control_commands: dict[str, Any] = {}

    def add_default_control_commands(self, enabled=True):
        # for things that can take longer:
        try:
            from xpra.server.control_command import HelloCommand, HelpCommand, DebugControl, DisabledCommand
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
        code, response = self.process_control_command(proto, *args)
        hello = {"command_response": (code, response)}
        proto.send_now(("hello", hello))

    def process_control_command(self, protocol, *args):
        try:
            options = protocol._conn.options
            control = options.get("control", "yes")
        except AttributeError:
            control = "no"
        if not str_to_bool(control):
            err = "control commands are not enabled on this connection"
            log.warn(f"Warning: {err}")
            return 6, err
        from xpra.server.control_command import ControlError
        if not args:
            err = "control command must have arguments"
            log.warn(f"Warning: {err}")
            return 6, err
        name = args[0]
        try:
            command = self.control_commands.get(name) or self.control_commands.get("*")
            log(f"process_control_command control_commands[{name}]={command}")
            if not command:
                log.warn(f"Warning: invalid command: {name!r}")
                log.warn(f" must be one of: {csv(self.control_commands)}")
                return 6, "invalid command"
            log(f"process_control_command calling {command.run}({args[1:]})")
            v = command.run(*args[1:])
            return 0, v
        except ControlError as e:
            log.error(f"error {e.code} processing control command {name}")
            msgs = [f" {e}"]
            if e.help:
                msgs.append(f" {name!r}: {e.help}")
            for msg in msgs:
                log.error(msg)
            return e.code, "\n".join(msgs)
        except Exception as e:
            log.error(f"error processing control command {name!r}", exc_info=True)
            return 127, f"error processing control command: {e}"
