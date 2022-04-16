#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2016-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import socket
import unittest

from xpra.util import typedict
from xpra.os_util import pollwait, which, OSX, POSIX
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.server.shadow.shadow_server_base import REFRESH_DELAY
from unit.server_test_util import ServerTestUtil


class ShadowServerTest(ServerTestUtil):

	def start_shadow_server(self, *args):
		display = self.find_free_display()
		xvfb = self.start_Xvfb(display)
		assert display in self.find_X11_displays()
		#start server using this display:
		server = self.check_server("shadow", display, *args)
		return display, xvfb, server

	def stop_shadow_server(self, xvfb, server):
		self.check_stop_server(server, "stop", xvfb.display)
		time.sleep(1)
		assert pollwait(xvfb, 2) is None, "the Xvfb should not have been killed by xpra shutting down!"
		xvfb.terminate()

	def test_shadow_start_stop(self):
		_, xvfb, server = self.start_shadow_server()
		self.stop_shadow_server(xvfb, server)

	def test_dbus_interface(self):
		if not POSIX or OSX:
			return
		dbus_send = which("dbus-send")
		if not dbus_send:
			print("Warning: dbus test skipped, 'dbus-send' not found")
			return
		display, xvfb, server = self.start_shadow_server("-d", "dbus")
		info = self.get_server_info(xvfb.display)
		assert info
		tinfo = typedict(info)
		idisplay = tinfo.strget("server.display")
		assert idisplay==display, "expected display '%s' in info, but got '%s'" % (display, idisplay)
		rd = tinfo.intget("refresh-delay", 0)
		assert rd==REFRESH_DELAY, "expected refresh-delay=%i, got %i" % (REFRESH_DELAY, rd)
		dstr = display.lstrip(":")
		new_delay = 2
		cmd = [dbus_send, "--session", "--type=method_call",
				"--dest=org.xpra.Server%s" % dstr, "/org/xpra/Server",
				"org.xpra.Server.SetRefreshDelay", "int32:%i" % new_delay]
		env = self.get_run_env()
		env["DISPLAY"] = display
		self.run_command(cmd, env=env).wait(20)
		#check that the value has changed:
		info = self.get_server_info(display)
		assert info
		tinfo = typedict(info)
		assert tinfo.strget("server.display")==display
		rd = tinfo.intget("refresh-delay", 0)
		assert rd==new_delay, "expected refresh-delay=%i, got %i" % (new_delay, rd)
		self.stop_shadow_server(xvfb, server)


	def test_root_window_model(self):
		from xpra.server.shadow.root_window_model import RootWindowModel
		W = 640
		H = 480
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
				return (0, 0, W, H)
		class FakeCapture:
			def take_screenshot(self):
				return self.get_image(0, 0, W, H)
			def get_image(self, x, y, w, h):
				pixels = "0"*w*4*h
				return ImageWrapper(x, y, w, h, pixels, "BGRA", 32, w*4, 4, ImageWrapper.PACKED, True, None)
			def get_info(self):
				return {"type" : "fake"}
		window = FakeRootWindow()
		rwm = RootWindowModel(window, FakeCapture(), geometry=window.get_geometry()[:4])
		assert repr(rwm)
		assert rwm.get_info()
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
		rwm.suspend()
		rwm.unmanage(True)
		assert rwm.take_screenshot()
		assert rwm.get_image(10, 10, 20, 20)
		rwm.geometry = (10, 10, W, H)
		img = rwm.get_image(10, 10, 20, 20)
		assert img.get_target_x()==10
		assert img.get_target_y()==10


def main():
	if POSIX and not OSX:
		unittest.main()


if __name__ == '__main__':
	main()
