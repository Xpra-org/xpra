#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.os_util import PYTHON3
from xpra.util import AdHocStruct, typedict
from xpra.client.mixins.webcam import WebcamForwarder
from unit.client.mixins.clientmixintest_util import ClientMixinTest


class WebcamTest(ClientMixinTest):

	def test_webcam(self):
		x = WebcamForwarder()
		self.mixin = x
		opts = AdHocStruct()
		opts.webcam = "on"
		x.init(opts)
		x.send = self.send
		x.idle_add = self.glib.idle_add
		x.timeout_add = self.glib.timeout_add
		x.source_remove = self.glib.source_remove
		assert x.get_caps() is not None
		x.server_capabilities = typedict({
			"webcam" : True,
			"webcam.encodings" : ("png", "jpeg"),
			"virtual-video-devices" : 1,
			})
		if x.webcam_forwarding>0:
			self.glib.timeout_add(2500, x.stop_sending_webcam)
			self.glib.timeout_add(5000, self.stop)
			x.parse_server_capabilities()
			self.main_loop.run()
			print("packets=%s" % (self.packets,))
			assert len(self.packets)>2
			assert self.verify_packet(0, ("webcam-start", 0, ))
			assert self.verify_packet(1, ("webcam-frame", 0, ))
			assert self.verify_packet(-1, ("webcam-stop", 0, ))

def main():
	if PYTHON3:
		unittest.main()


if __name__ == '__main__':
	main()
