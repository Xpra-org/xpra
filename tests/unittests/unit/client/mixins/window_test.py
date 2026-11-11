#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.util import AdHocStruct
from unit.process_test_util import DisplayContext
from unit.client.mixins.clientmixintest_util import ClientMixinTest


class WindowManagerTest(ClientMixinTest):

	def test_auto_refresh_delay_caps(self):
		from xpra.client.mixins import window_manager
		client = window_manager.WindowClient()
		client.get_mouse_position = lambda: (0, 0)
		for seconds, milliseconds in ((0.15, 150), (0.5, 500), (0, 0)):
			with self.subTest(seconds=seconds):
				client.auto_refresh_delay = seconds
				with patch.object(window_manager, "get_double_click_time", return_value=250), \
						patch.object(window_manager, "get_double_click_distance", return_value=(5, 5)):
					caps = client.get_caps()
				self.assertEqual(caps["encoding.auto_refresh_delay"], milliseconds)
				self.assertEqual(caps["auto_refresh_delay"], milliseconds)

	def test_windowmanager(self):
		with DisplayContext():
			from xpra.client.mixins.window_manager import WindowClient
			def _WindowClient():
				def get_mouse_position():
					return 0, 0
				wc = WindowClient()
				wc.get_mouse_position = get_mouse_position
				return wc
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
			opts.tray_icon = "yes"
			self._test_mixin_class(_WindowClient, opts)

def main():
	unittest.main()


if __name__ == '__main__':
	main()
