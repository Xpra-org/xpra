# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Callable

from xpra.common import noop
from xpra.net.common import may_log_packet, Packet, PacketHandlerType, BACKWARDS_COMPATIBLE
from xpra.log import Logger

log = Logger("network")


class PacketDispatcher:

    def __init__(self):
        self._authenticated_packet_handlers: dict[str, Callable] = {}
        self._authenticated_ui_packet_handlers: dict[str, Callable] = {}
        self._default_packet_handlers: dict[str, Callable] = {}
        self.packet_alias: dict[str, str] = {}

    def get_info(self) -> dict[str, Any]:
        return {
            "packet-handlers": {
                "authenticated": sorted(self._authenticated_packet_handlers.keys()),
                "ui": sorted(self._authenticated_ui_packet_handlers.keys()),
            },
        }

    def remove_packet_handlers(self, *keys) -> None:
        for k in keys:
            for d in (
                    self._authenticated_packet_handlers,
                    self._authenticated_ui_packet_handlers,
                    self._default_packet_handlers,
            ):
                d.pop(k, None)

    def add_packet_handlers(self, defs: dict[str, PacketHandlerType], main_thread=False) -> None:
        for packet_type, handler in defs.items():
            self.add_packet_handler(packet_type, handler, main_thread)

    def add_packet_handler(self, packet_type: str, handler: PacketHandlerType, main_thread=False) -> None:
        # replace any previously defined handlers:
        self.remove_packet_handlers(packet_type)
        log("add_packet_handler%s", (packet_type, handler, main_thread))
        handlers = self._authenticated_ui_packet_handlers if main_thread else self._authenticated_packet_handlers
        handlers[packet_type] = handler

    def add_packets(self, *packet_types: str, main_thread=False) -> None:
        for packet_type in packet_types:
            handler = getattr(self, "_process_" + packet_type.replace("-", "_"))
            self.add_packet_handler(packet_type, handler, main_thread)

    def add_legacy_alias(self, legacy_name: str, new_name: str) -> None:
        if BACKWARDS_COMPATIBLE:
            self.packet_alias[legacy_name] = new_name

    def dispatch_packet(self, proto, packet: Packet, authenticated=False) -> None:
        ptype = packet.get_type()
        packet_type = self.packet_alias.get(ptype, ptype)
        if packet_type != ptype:
            # re-write the packet with the new packet name:
            packet = Packet(packet_type, *packet[1:])
        handler: Callable = noop

        def call_handler(main: bool) -> None:
            may_log_packet(False, packet_type, packet)
            try:
                self.call_packet_handler(main, handler, proto, packet)
            except (AssertionError, TypeError, ValueError, RuntimeError):
                log.error(f"Error processing {packet_type!r}", exc_info=True)

        try:
            if authenticated:
                handler = self._authenticated_ui_packet_handlers.get(packet_type)
                if handler:
                    log("process ui packet %s", packet_type)
                    call_handler(True)
                    return
                handler = self._authenticated_packet_handlers.get(packet_type)
                if handler:
                    log("process non-ui packet %s", packet_type)
                    call_handler(False)
                    return
            handler = self._default_packet_handlers.get(packet_type)
            if handler:
                log("process default packet %s", packet_type)
                call_handler(False)
                return

            self.call_packet_handler(True, self.handle_invalid_packet, proto, packet)
        except (RuntimeError, AssertionError):
            log.error(f"Error processing a {packet_type!r} packet")
            log.error(f" received from {proto}:")
            log.error(f" using {handler}", exc_info=True)

    @staticmethod
    def call_packet_handler(main: bool, handler: PacketHandlerType, proto, packet: Packet) -> None:
        # subclasses should handle the `main` flag and call the handler from the main thread when set
        handler(proto, packet)

    @staticmethod
    def handle_invalid_packet(proto, packet: Packet) -> None:
        if proto.is_closed():
            return
        packet_type = packet.get_type()
        log("invalid packet: %s", packet)
        log.error(f"Error: unknown or invalid packet type {packet_type!r}")
        log.error(f" received from {proto}")
        proto.close()
