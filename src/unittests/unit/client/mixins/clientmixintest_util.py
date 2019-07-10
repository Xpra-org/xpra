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

	def stop(self):
		self.glib.timeout_add(1000, self.main_loop.quit)

	def send(self, *args):
		self.packets.append(args)

	def verify_packet(self, index, expected):
		if index<0:
			actual_index = len(self.packets)+index
		else:
			actual_index = index
		assert actual_index>=0
		assert len(self.packets)>actual_index, "not enough packets (%i) to access %i" % (len(self.packets), index)
		packet = self.packets[actual_index]
		pslice = packet[:len(expected)]
		return pslice==expected
