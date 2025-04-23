# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Callable

from xpra.common import noop
from xpra.os_util import gi_import
from xpra.net.common import may_log_packet
from xpra.net.common import ServerPacketHandlerType
from xpra.log import Logger

log = Logger("server")

GLib = gi_import("GLib")


class GLibPacketHandler:

    def __init__(self):
        self._authenticated_packet_handlers: dict[str, Callable] = {}
        self._authenticated_ui_packet_handlers: dict[str, Callable] = {}
        self._default_packet_handlers: dict[str, Callable] = {}
        self.packet_alias: dict[str, str] = {}

    def get_info(self) -> dict[str, Any]:
        return {
            "packet-handlers" : {
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

    def add_packet_handlers(self, defs: dict[str, ServerPacketHandlerType], main_thread=False) -> None:
        for packet_type, handler in defs.items():
            self.add_packet_handler(packet_type, handler, main_thread)

    def add_packet_handler(self, packet_type: str, handler: ServerPacketHandlerType, main_thread=False) -> None:
        log("add_packet_handler%s", (packet_type, handler, main_thread))
        # replace any previously defined handlers:
        self.remove_packet_handlers(packet_type)
        if main_thread:
            handlers = self._authenticated_ui_packet_handlers
        else:
            handlers = self._authenticated_packet_handlers
        handlers[packet_type] = handler

    def add_packets(self, *packet_types: str, main_thread=False) -> None:
        for packet_type in packet_types:
            handler = getattr(self, "_process_" + packet_type.replace("-", "_"))
            self.add_packet_handler(packet_type, handler, main_thread)

    def add_legacy_alias(self, legacy_name, new_name) -> None:
        self.packet_alias[legacy_name] = new_name

    def dispatch_packet(self, proto, packet, authenticated=False) -> None:
        packet_type = str(packet[0])
        packet_type = self.packet_alias.get(packet_type, packet_type)
        handler: Callable = noop

        def call_handler() -> None:
            may_log_packet(False, packet_type, packet)
            self.call_packet_handler(handler, proto, packet)

        try:

            if authenticated:
                handler = self._authenticated_ui_packet_handlers.get(packet_type)
                if handler:
                    log("process ui packet %s", packet_type)
                    GLib.idle_add(call_handler)
                    return
                handler = self._authenticated_packet_handlers.get(packet_type)
                if handler:
                    log("process non-ui packet %s", packet_type)
                    call_handler()
                    return
            handler = self._default_packet_handlers.get(packet_type)
            if handler:
                log("process default packet %s", packet_type)
                call_handler()
                return

            GLib.idle_add(self.handle_invalid_packet, proto, packet)
        except (RuntimeError, AssertionError):
            log.error(f"Error processing a {packet_type!r} packet")
            log.error(f" received from {proto}:")
            log.error(f" using {handler}", exc_info=True)

    @staticmethod
    def call_packet_handler(handler: Callable, proto, packet) -> None:
        handler(proto, packet)

    @staticmethod
    def handle_invalid_packet(proto, packet) -> None:
        if proto.is_closed():
            return
        packet_type = str(packet[0])
        log("invalid packet: %s", packet)
        log.error(f"Error: unknown or invalid packet type {packet_type!r}")
        log.error(f" received from {proto}")
        proto.close()
