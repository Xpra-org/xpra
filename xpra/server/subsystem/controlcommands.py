# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# pylint: disable-msg=E1101


from xpra.util.str_fn import csv
from xpra.common import noop
from xpra.net.common import Packet, PacketElement
from xpra.net.control.common import ArgsControlCommand, ControlError, parse_boolean_value
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger

log = Logger("command")

TOGGLE_FEATURES = (
    "bell", "randr", "cursors", "notifications", "clipboard",
    "start-new-commands", "client-shutdown", "webcam",
)


class ServerBaseControlCommands(StubServerMixin):
    """
    Control commands for ServerBase
    """
    PREFIX = "control"

    def setup(self) -> None:
        self.add_control_commands()

    def add_control_commands(self) -> None:
        for cmd in (
                # server globals:
                ArgsControlCommand("toggle-feature",
                                   "toggle a server feature on or off, one of: %s" % csv(TOGGLE_FEATURES), min_args=1,
                                   max_args=2, validation=[str, parse_boolean_value]),

                ArgsControlCommand("compression", "sets the packet compressor", min_args=1, max_args=1),
                ArgsControlCommand("encoder", "sets the packet encoder", min_args=1, max_args=1),

                ArgsControlCommand("set-ui-driver", "set the client connection driving the session", min_args=1,
                                   max_args=1),
                # session and clients:
                ArgsControlCommand("client", "forwards a control command to the client(s)", min_args=1),
                ArgsControlCommand("client-property", "set a client property", min_args=4, max_args=5,
                                   validation=[int]),
        ):
            cmd.do_run = getattr(self, "control_command_%s" % cmd.name.replace("-", "_"), noop)
            if cmd.do_run != noop:
                self.add_control_command(cmd.name, cmd)

    def control_command_toggle_feature(self, feature: str, state: str) -> str:
        log("control_command_toggle_feature(%s, %s)", feature, state)
        if feature not in TOGGLE_FEATURES:
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
        self.setting_changed(feature, state)
        return f"{feature} set to {state} (was {cur!r}"

    def control_command_remove_window_filters(self) -> str:
        # modify the existing list object,
        # which is referenced by all the sources
        count = len(self.window_filters)
        self.window_filters[:] = []
        return f"removed {count} window-filters"

    def control_command_add_window_filter(self, object_name: str, property_name: str, operator: str, value,
                                          client_uuids="") -> str:
        from xpra.server.window import filters  # pylint: disable=import-outside-toplevel
        window_filter = filters.get_window_filter(object_name, property_name, operator, value)
        # log("%s%s=%s", filters.get_window_filter, (object_name, property_name, operator, value), window_filter)
        if client_uuids == "*":
            # applies to all sources:
            self.window_filters.append(("*", window_filter))
        else:
            for client_uuid in client_uuids.split(","):
                self.window_filters.append((client_uuid, window_filter))
        return f"added window-filter: {window_filter} for client uuids={client_uuids}"

    def control_command_compression(self, compress: str) -> str:
        c = compress.lower()
        from xpra.net import compression  # pylint: disable=import-outside-toplevel
        opts = compression.get_enabled_compressors()  # ie: [lz4, zlib]
        if c not in opts:
            raise ControlError("compressor argument must be one of: " + csv(opts))
        for cproto in tuple(self._server_sources.keys()):
            cproto.enable_compressor(c)
        self.all_send_client_command(f"enable_{c}")
        return f"compressors set to {compression}"

    def control_command_encoder(self, encoder: str) -> str:
        e = encoder.lower()
        from xpra.net import packet_encoding  # pylint: disable=import-outside-toplevel
        opts = packet_encoding.get_enabled_encoders()  # ie: [rencodeplus, ]
        if e not in opts:
            raise ControlError("encoder argument must be one of: " + csv(opts))
        for cproto in tuple(self._server_sources.keys()):
            cproto.enable_encoder(e)
        self.all_send_client_command(f"enable_{e}")
        return f"encoders set to {encoder}"

    def all_send_client_command(self, command: str, *args: PacketElement) -> None:
        """ forwards the command to all clients """
        for source in tuple(self._server_sources.values()):
            # forwards to *the* client, if there is *one*
            if command not in source.client_control_commands:
                log.info(f"client command {command!r} not forwarded to client {source} (not supported)")
            else:
                source.send_client_command(command, *args)

    def control_command_client(self, command: str, *args: PacketElement) -> str:
        if command == "help":
            all_control_commands = []
            for source in tuple(self._server_sources.values()):
                all_control_commands += list(source.client_control_commands)
            return "clients support the following control commands: %s" % csv(all_control_commands)

        self.all_send_client_command(command, *args)
        return f"client control command {command!r} forwarded to clients"

    def control_command_client_property(self, wid: int, uuid, prop: str, value, conv=None) -> str:
        wid = int(wid)
        conv_fn = {
            "int": int,
            "float": float,
            "": str,
        }.get(conv)
        assert conv_fn
        typeinfo = "%s " % (conv or "string")
        value = conv_fn(value)
        self.client_properties.setdefault(wid, {}).setdefault(uuid, {})[prop] = value
        return f"property {prop!r} set to {typeinfo} value {value!r} for window {wid:#x}, client {uuid}"

    def control_command_set_ui_driver(self, uuid) -> str:
        ss = [s for s in self._server_sources.values() if s.uuid == uuid]
        if not ss:
            return f"source not found for uuid {uuid!r}"
        if len(ss) > 1:
            return f"more than one source found for uuid {uuid!r}"
        self.set_ui_driver(ss)
        return f"ui-driver set to {ss}"

    def _process_control_request(self, protocol, packet: Packet) -> None:
        """ client sent a command request through its normal channel """
        assert len(packet) >= 2, "invalid command request packet (too small!)"
        # packet[0] = "control"
        # this may end up calling do_handle_command_request via the adapter
        code, msg = self.process_control_command(protocol, *packet[1:])
        log("command request returned: %s (%s)", code, msg)

    def init_packet_handlers(self) -> None:
        self.add_packets(f"{ServerBaseControlCommands.PREFIX}-request")
        self.add_legacy_alias("command_request", f"{ServerBaseControlCommands.PREFIX}-request")
