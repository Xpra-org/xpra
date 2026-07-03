#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from collections.abc import Callable

from xpra.common import noop
from xpra.net.common import Packet, BACKWARDS_COMPATIBLE
from xpra.util.objects import typedict, AdHocStruct
from xpra.log import Logger
from xpra.os_util import gi_import

GLib = gi_import("GLib")


def debug_all() -> None:
    from xpra.log import enable_debug_for
    enable_debug_for("all")


class ClientMixinTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        super(ClientMixinTest, cls).setUpClass()
        cls.glib = GLib
        cls.main_loop = cls.glib.MainLoop()

    def setUp(self):
        self.packets = []
        self.mixin = None
        self.packet_handlers = {}
        self.exit_codes = []
        self.legacy_alias = {}

    def tearDown(self):
        unittest.TestCase.tearDown(self)
        if mixin := self.mixin:
            self.mixin = None
            mixin.cleanup()

    def stop(self) -> None:
        self.glib.timeout_add(1000, self.main_loop.quit)

    def dump_packets(self) -> None:
        from xpra.util.io import get_util_logger
        log = get_util_logger()
        log.info("dump_packets() %i packets to send:", len(self.packets))
        for x in self.packets:
            log.info("%s", x)

    def send(self, *args) -> None:
        self.packets.append(args)

    def send_now(self, *args) -> None:
        self.packets.append(args)

    def get_packet(self, index: int):
        if index < 0:
            actual_index = len(self.packets)+index
        else:
            actual_index = index
        assert actual_index >= 0, "invalid actual index %i for index %i" % (actual_index, index)
        assert len(self.packets) > actual_index, "not enough packets (%i) to access %i" % (len(self.packets), index)
        return self.packets[actual_index]

    def verify_packet(self, index: int, expected) -> None:
        packet = self.get_packet(index)
        pslice = packet[:len(expected)]
        if pslice != expected:
            log = Logger("test")
            log.error(f"packet mismatch at index {index}")
            for i, packet in enumerate(self.packets):
                log.error("[%3i] %s", i, packet)
            raise RuntimeError("invalid packet slice %s, expected %s" % (pslice, expected))

    def add_legacy_alias(self, legacy_name: str, name: str) -> None:
        if BACKWARDS_COMPATIBLE:
            self.legacy_alias[legacy_name] = name

    def add_packet_handler(self, packet_type: str, handler: Callable, main_thread=False):
        # log("add_packet_handler%s", (packet_type, handler, main_thread))
        self.packet_handlers[packet_type] = handler

    def add_packets(self, *packet_types: str, main_thread=False) -> None:
        for packet_type in packet_types:
            handler = getattr(self.mixin, "_process_" + packet_type.replace("-", "_"))
            self.add_packet_handler(packet_type, handler, main_thread)

    def handle_packet(self, packet: Packet | tuple) -> None:
        if isinstance(packet, tuple):
            packet = Packet(*packet)
        packet_type = packet.get_type()
        ph = self.packet_handlers.get(packet_type)
        assert ph is not None, "no packet handler for %s" % packet_type
        ph(packet)

    def fake_quit(self, code) -> None:
        self.exit_codes.append(code)

    def get_mouse_position(self) -> tuple[int, int]:
        # stand-in for the toolkit client's pointer query,
        # used by the `pointer` subsystem via `self.client`:
        return 0, 0

    def get_raw_mouse_position(self) -> tuple[int, int]:
        return 0, 0

    def _test_mixin_class(self, mclass, opts, caps=None, protocol_type="xpra"):
        x = self.mixin = mclass()
        # subsystems are always owned by a client and reach it via `self.client`
        # (`send`, `quit`, `add_packet_handler`, ... all delegate to it);
        # this test harness stands in for the owning client:
        x.client = self
        self.exit_code = None
        self.readonly = False
        self.session_name = ""
        self.display_desc = {}
        self.quit = self.fake_quit
        self.connect = noop
        self.emit = noop
        # a test may set this itself before calling `_test_mixin_class`
        # (ie: to actually run the deferred callback via the glib loop):
        if not hasattr(self, "after_handshake"):
            self.after_handshake = noop
        self._ui_event = noop
        self.on_server_setting_changed = noop
        # the notification subsystem composes its notifier list via the client's
        # `get_notifier_classes()`; when testing it in isolation, expose just the
        # subsystem's own native notifiers as that client method:
        if hasattr(x, "get_native_notifier_classes"):
            self.get_notifier_classes = x.get_native_notifier_classes
        # the tray subsystem consumes the client's menu-helper service and its
        # composed `get_tray_classes()`; when testing it in isolation, stand in a
        # no-op menu helper and expose the subsystem's own native tray classes:
        if hasattr(x, "get_native_tray_classes"):
            self.get_menu_helper = noop
            self.get_tray_classes = x.get_native_tray_classes
        fake_protocol = AdHocStruct()
        fake_protocol.get_info = lambda: {}
        fake_protocol.set_compression_level = lambda _x: None
        fake_protocol.TYPE = protocol_type
        fake_protocol.enable_encoder_from_caps = noop
        self._protocol = fake_protocol
        x.init(opts)
        x.load()
        conn = AdHocStruct()
        conn.filename = "/fake/path/to/nowhere"
        x.setup_connection(conn)
        x.init_authenticated_packet_handlers()
        caps = self.make_caps(caps)
        x.parse_server_capabilities(caps)
        assert x.get_caps() is not None
        assert x.get_info() is not None
        return x

    def make_caps(self, caps=None) -> typedict:
        return typedict(caps or {})
