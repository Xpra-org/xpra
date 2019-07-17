#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

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
