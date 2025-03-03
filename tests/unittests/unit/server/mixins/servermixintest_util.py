#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from gi.repository import GLib  # @UnresolvedImport

from xpra.util.objects import typedict, AdHocStruct
from xpra.server.source.stub_source_mixin import StubSourceMixin


class ServerMixinTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        super(ServerMixinTest, cls).setUpClass()
        cls.glib = GLib
        cls.main_loop = cls.glib.MainLoop()

    def setUp(self):
        self.mixin = None
        self.source = None
        self.protocol = None
        self.packet_handlers = {}
        self.legacy_alias = {}

    def tearDown(self):
        unittest.TestCase.tearDown(self)
        if self.source:
            self.source.cleanup()
            self.source = None
        if self.mixin:
            self.mixin.cleanup()
            self.mixin = None

    def debug_all(self) -> None:
        from xpra.log import enable_debug_for
        enable_debug_for("all")

    def stop(self) -> None:
        self.glib.timeout_add(1000, self.main_loop.quit)

    def wait_for_threaded_init(self):
        # we don't do threading yet,
        # so no need to wait
        pass

    def add_packets(self, *packet_types: str, main_thread=True) -> None:
        for packet_type in packet_types:
            handler = getattr(self.mixin, "_process_" + packet_type.replace("-", "_"))
            self.add_packet_handler(packet_type, handler, main_thread)

    def add_legacy_alias(self, legacy_name: str, name: str) -> None:
        self.legacy_alias[legacy_name] = name

    def add_packet_handler(self, packet_type: str, handler=None, main_thread=True) -> None:
        self.packet_handlers[packet_type] = handler

    def handle_packet(self, packet):
        packet_type = packet[0]
        packet_type = self.legacy_alias.get(packet_type, packet_type)
        ph = self.packet_handlers.get(packet_type)
        assert ph is not None, "no packet handler for %s" % packet_type
        ph(self.protocol, packet)

    def verify_packet_error(self, packet):
        try:
            self.handle_packet(packet)
        except Exception:
            pass
        else:
            raise Exception("invalid packet %s should cause an error" % (packet,))

    def get_server_source(self, proto):
        assert proto==self.protocol
        return self.source

    def create_test_sockets(self):
        return {}

    def _test_mixin_class(self, mclass, opts, caps=None, source_mixin_class=StubSourceMixin):
        x = self.mixin = mclass()
        x._server_sources = {}   # pylint: disable=protected-access
        x.wait_for_threaded_init = self.wait_for_threaded_init
        x.add_packets = self.add_packets
        x.add_legacy_alias = self.add_legacy_alias
        x.add_packet_handler = self.add_packet_handler
        x.get_server_source = self.get_server_source
        x.init_state()
        x.init(opts)
        x.auth_classes = {}
        x.init_sockets(self.create_test_sockets())
        x.setup()
        x.threaded_setup()
        x.init_packet_handlers()
        caps = typedict(caps or {})
        send_ui = True
        self.source = None
        if source_mixin_class:
            self.source = source_mixin_class()
            self.protocol = AdHocStruct()
            self.protocol.TYPE = "xpra"
            self.source.wants = ("display", "foo")
            self.source.protocol = self.protocol
            self.source.init_from(self.protocol, x)
            self.source.init_state()
            self.source.parse_client_caps(caps)
            self.source.get_info()
        x.get_caps(self.source)
        x.get_info(None)
        x.parse_hello(self.source, caps, send_ui)
        x.get_info(self.source)
