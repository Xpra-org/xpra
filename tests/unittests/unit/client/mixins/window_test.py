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

	def test_cursor_hotspot_is_clamped(self):
		from xpra.client.mixins.window_manager import WindowClient
		client = WindowClient()
		client.cursors_enabled = True
		pixels = b"\0" * 8
		with patch.object(client, "set_windows_cursor") as set_windows_cursor:
			for w, h, xhot, yhot, expected in ((1, 2, 0, 2, (0, 1)), (2, 1, 2, 0, (1, 0))):
				with self.subTest(size=(w, h), hotspot=(xhot, yhot)):
					client._process_cursor(("cursor", "raw", 0, 0, w, h, xhot, yhot, 1, pixels, ""))
					expected_cursor = ["raw", 0, 0, w, h, *expected, 1, pixels, ""]
					self.assertEqual(set_windows_cursor.call_args.args[1], expected_cursor)

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

	def test_mousewheel_disabled(self):
		from xpra.client.mixins.window_manager import WindowClient
		from xpra.scripts.config import dict_to_validated_config
		opts = dict_to_validated_config({"mousewheel": "no", "border": ""})
		for packet_type in ("pointer-button", "button-action"):
			with self.subTest(packet_type=packet_type):
				client = WindowClient()
				client.init(opts)
				client.server_packet_types = (packet_type,)
				client.next_pointer_sequence = lambda _device_id: 1
				sent = []
				client.send_positional = sent.append
				for button in (4, 5):
					for pressed in (True, False):
						client.send_button(-1, 1, button, pressed, (100, 200), (), (), {})
				self.assertEqual(sent, [])
				client.send_button(-1, 1, 1, True, (100, 200), (), (), {})
				self.assertEqual([packet[0] for packet in sent], [packet_type])

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
