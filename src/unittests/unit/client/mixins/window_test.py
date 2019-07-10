#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

from xpra.os_util import POSIX, OSX
from xpra.util import AdHocStruct, typedict
from unit.client.mixins.clientmixintest_util import ClientMixinTest


class WindowManagerTest(ClientMixinTest):

	def test_webcam(self):
		if os.environ.get("DISPLAY") and POSIX and not OSX and os.environ.get("GDK_BACKEND", "x11")=="x11":
			from xpra.x11.gtk_x11.gdk_display_source import init_gdk_display_source
			init_gdk_display_source()
		from xpra.client.mixins.window_manager import WindowClient
		x = WindowClient()
		self.mixin = x
		def get_mouse_position():
			return 0, 0
		x.get_mouse_position = get_mouse_position
		opts = AdHocStruct()
		opts.system_tray = True
		opts.cursors = True
		opts.bell = True
		opts.input_devices = True
		opts.auto_refresh_delay = 0
		opts.min_size = "100x100"
		opts.max_size = "2000x2000"
		opts.pixel_depth = 24
		opts.windows = True
		opts.window_close = "forward"
		opts.modal_windows = True
		opts.border = "red"
		opts.mousewheel = "yes"
		x.init(opts)
		x.send = self.send
		x.idle_add = self.glib.idle_add
		x.timeout_add = self.glib.timeout_add
		x.source_remove = self.glib.source_remove
		assert x.get_caps() is not None
		x.server_capabilities = typedict({
			})
		x.parse_server_capabilities()

def main():
	unittest.main()


if __name__ == '__main__':
	main()
