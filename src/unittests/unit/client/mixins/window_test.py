#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct
from unit.process_test_util import DisplayContext
from unit.client.mixins.clientmixintest_util import ClientMixinTest


class WindowManagerTest(ClientMixinTest):

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
			self._test_mixin_class(_WindowClient, opts)

def main():
	unittest.main()


if __name__ == '__main__':
	main()
