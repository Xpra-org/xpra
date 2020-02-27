#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import socket
import unittest

from xpra.os_util import pollwait, OSX, POSIX
from unit.server_test_util import ServerTestUtil


class ShadowServerTest(ServerTestUtil):

	def test_shadow_start_stop(self):
		display = self.find_free_display()
		xvfb = self.start_Xvfb(display)
		time.sleep(1)
		assert display in self.find_X11_displays()
		#start server using this display:
		server = self.check_server("shadow", display)
		self.check_stop_server(server, "stop", display)
		time.sleep(1)
		assert pollwait(xvfb, 2) is None, "the Xvfb should not have been killed by xpra shutting down!"
		xvfb.terminate()

	def test_root_window_model(self):
		from xpra.server.shadow.root_window_model import RootWindowModel
		class FakeDisplay:
			def get_name(self):
				return "fake-display"
		class FakeScreen:
			def get_display(self):
				return FakeDisplay()
		class FakeRootWindow:
			def get_screen(self):
				return FakeScreen()
			def get_geometry(self):
				return (0, 0, 640, 480)
		class FakeCapture:
			def take_screenshot(self):
				return None
		rwm = RootWindowModel(FakeRootWindow(), FakeCapture())
		assert repr(rwm)
		rwm.get_default_window_icon(32)
		for prop in ("title", "class-instance", "size-hints", "icons"):
			rwm.get_property(prop)
		for prop, value in {
			"client-machine"	: socket.gethostname(),
			"window-type"		: ["NORMAL"],
			"fullscreen"		: False,
			"shadow"			: True,
			"depth"				: 24,
			"scaling"			: None,
			"opacity"			: None,
			"content-type"		: "desktop",
			}.items():
			assert rwm.get_property(prop)==value

def main():
	if POSIX and not OSX:
		unittest.main()


if __name__ == '__main__':
	main()
