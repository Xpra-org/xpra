#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import typedict, AdHocStruct
from xpra.gtk_common.gobject_compat import import_glib


class ClientMixinTest(unittest.TestCase):

	@classmethod
	def setUpClass(cls):
		super(ClientMixinTest, cls).setUpClass()
		cls.glib = import_glib()
		cls.main_loop = cls.glib.MainLoop()

	def setUp(self):
		self.packets = []
		self.mixin = None
		self.packet_handlers = {}

	def tearDown(self):
		unittest.TestCase.tearDown(self)
		if self.mixin:
			self.mixin.cleanup()
			self.mixin = None

	def stop(self):
		self.glib.timeout_add(1000, self.main_loop.quit)

	def debug_all(self):
		from xpra.log import enable_debug_for
		enable_debug_for("all")

	def dump_packets(self):
		from xpra.os_util import get_util_logger
		log = get_util_logger()
		log.info("dump_packets() %i packets to send:", len(self.packets))
		for x in self.packets:
			log.info("%s", x)


	def send(self, *args):
		self.packets.append(args)

	def get_packet(self, index):
		if index<0:
			actual_index = len(self.packets)+index
		else:
			actual_index = index
		assert actual_index>=0, "invalid actual index %i for index %i" % (actual_index, index)
		assert len(self.packets)>actual_index, "not enough packets (%i) to access %i" % (len(self.packets), index)
		return self.packets[actual_index]

	def verify_packet(self, index, expected):
		packet = self.get_packet(index)
		pslice = packet[:len(expected)]
		assert pslice==expected, "invalid packet slice %s, expected %s" % (pslice, expected)


	def add_packet_handler(self, packet_type, handler, _main_thread=True):
		self.packet_handlers[packet_type] = handler

	def add_packet_handlers(self, defs, _main_thread=True):
		self.packet_handlers.update(defs)

	def handle_packet(self, packet):
		packet_type = packet[0]
		ph = self.packet_handlers.get(packet_type)
		assert ph is not None, "no packet handler for %s" % packet_type
		ph(packet)


	def _test_mixin_class(self, mclass, opts, caps=None):
		x = self.mixin = mclass()
		fake_protocol = AdHocStruct()
		fake_protocol.get_info = lambda : {}
		fake_protocol.set_compression_level = lambda _x : None
		x._protocol = fake_protocol
		x.add_packet_handlers = self.add_packet_handlers
		x.add_packet_handler = self.add_packet_handler
		x.idle_add = self.glib.idle_add
		x.timeout_add = self.glib.timeout_add
		x.source_remove = self.glib.source_remove
		x.init(opts)
		conn = AdHocStruct()
		conn.filename = "/tmp/fake"
		x.setup_connection(conn)
		x.send = self.send
		x.send_now = self.send
		x.add_packet_handlers = self.add_packet_handlers
		x.add_packet_handler = self.add_packet_handler
		x.init_authenticated_packet_handlers()
		x.server_capabilities = typedict(caps or {})
		x.parse_server_capabilities()
		x.process_ui_capabilities()
		assert x.get_caps() is not None
		return x

	def make_caps(self, caps):
		return typedict(caps or {})
