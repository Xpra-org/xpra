#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from gi.repository import GLib

from xpra.util import typedict, AdHocStruct
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

    def tearDown(self):
        unittest.TestCase.tearDown(self)
        if self.source:
            self.source.cleanup()
            self.source = None
        if self.mixin:
            self.mixin.cleanup()
            self.mixin = None

    def debug_all(self):
        from xpra.log import enable_debug_for
        enable_debug_for("all")

    def stop(self):
        self.glib.timeout_add(1000, self.main_loop.quit)

    def wait_for_threaded_init(self):
        #we don't do threading yet,
        #so no need to wait
        pass

    def add_packet_handler(self, packet_type, handler, _main_thread=True):
        self.packet_handlers[packet_type] = handler

    def add_packet_handlers(self, defs, _main_thread=True):
        self.packet_handlers.update(defs)

    def handle_packet(self, packet):
        packet_type = packet[0]
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
        x._server_sources = {}
        x.wait_for_threaded_init = self.wait_for_threaded_init
        x.add_packet_handlers = self.add_packet_handlers
        x.add_packet_handler = self.add_packet_handler
        x.get_server_source = self.get_server_source
        x.idle_add = self.glib.idle_add
        x.timeout_add = self.glib.timeout_add
        x.source_remove = self.glib.source_remove
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
            self.source.timeout_add = self.glib.timeout_add
            self.source.idle_add = self.glib.idle_add
            self.source.source_remove = self.glib.source_remove
            self.source.protocol = self.protocol
            self.source.init_from(self.protocol, x)
            self.source.init_state()
            self.source.parse_client_caps(caps)
            self.source.get_info()
        x.get_caps(self.source)
        x.get_info(None)
        x.parse_hello(self.source, caps, send_ui)
        x.get_info(self.source)
