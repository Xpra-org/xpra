# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.common import noop
from xpra.util.str_fn import csv
from xpra.net.common import Packet, PacketElement
from xpra.net.control.common import ControlCode, parse_boolean_value
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
            self.args_control("toggle-feature", "toggle a server feature on or off",
                              min_args=1, max_args=2, validation=[str, parse_boolean_value])
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

    def _process_control_request(self, protocol, packet: Packet) -> None:
        """ client sent a command request through its normal channel """
        assert len(packet) >= 2, "invalid command request packet (too small!)"
        # packet[0] = "control"
        # this may end up calling do_handle_command_request via the adapter
        code, msg = self.process_control_command(protocol, *packet[1:])
        log("command request returned: %s (%s)", code, msg)

    def init_packet_handlers(self) -> None:
        self.add_packets("control-request")
        self.add_legacy_alias("command_request", "control-request")

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

    def control_command_toggle_feature(self, feature: str, state: str) -> str:
        log("control_command_toggle_feature(%s, %s)", feature, state)
        features: set[str] = set()
        for cls in type(self).__mro__:
            for f in cls.__dict__.get("toggle_features", ()):
                features.add(f)
        if feature == "help":
            return "found the following features: %s" % csv(features)
        if feature not in features:
            msg = f"invalid feature {feature!r}"
            log.warn(msg)
            return msg
        fn = feature.replace("-", "_")
        if not hasattr(self, feature):
            msg = f"attribute {feature!r} not found - bug?"
            log.warn(msg)
            return msg
        cur = getattr(self, fn, None)
        setattr(self, fn, state)
        setting_changed = getattr(self, "setting_changed", noop)
        setting_changed(feature, state)
        return f"{feature} set to {state} (was {cur!r}"
