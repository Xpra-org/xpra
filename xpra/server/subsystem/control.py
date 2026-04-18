# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.util.str_fn import csv
from xpra.net.common import Packet, PacketElement
from xpra.net.control.common import ControlCode
from xpra.server.common import get_sources_by_type
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
            self.args_control("client", "forwards a control command to the client(s)", min_args=1)
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

    #########################################
    # Control Commands
    #########################################

    def control_command_client(self, command: str, *args: PacketElement) -> str:
        try:
            from xpra.server.source.control import ControlConnection
        except ImportError:
            return "no control support available"
        control_connections = get_sources_by_type(self, ControlConnection)
        if command == "help":
            all_control_commands = []
            for source in control_connections:
                all_control_commands += list(source.client_control_commands)
            return "clients may support the following control commands: %s" % csv(all_control_commands)

        count = 0
        for source in control_connections:
            # forwards to *the* client, if there is *one*
            if command not in source.client_control_commands:
                log.info(f"client command {command!r} not forwarded to client {source} (not supported)")
            else:
                source.send_client_command(command, *args)
                count += 1

        return f"client control command {command!r} forwarded to {count} clients"
