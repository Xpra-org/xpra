#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct
from xpra.client.mixins.webcam import WebcamForwarder
from unit.client.mixins.clientmixintest_util import ClientMixinTest


class WebcamTest(ClientMixinTest):

	def test_webcam(self):
		opts = AdHocStruct()
		opts.webcam = "on"
		self._test_mixin_class(WebcamForwarder, opts, {
			"webcam" : True,
			"webcam.encodings" : ("png", "jpeg"),
			"virtual-video-devices" : 1,
			})
		x = self.mixin
		if not x.webcam_device:
			print("no webcam device found, test skipped")
			return
		self.glib.timeout_add(2500, x.stop_sending_webcam)
		self.glib.timeout_add(5000, self.stop)
		self.main_loop.run()
		assert len(self.packets)>2
		self.verify_packet(0, ("webcam-start", 0, ))
		self.verify_packet(1, ("webcam-frame", 0, ))
		self.verify_packet(-1, ("webcam-stop", 0, ))

def main():
	unittest.main()


if __name__ == '__main__':
	main()
