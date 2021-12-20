#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct
from unit.test_util import silence_info
from unit.process_test_util import DisplayContext
from unit.client.mixins.clientmixintest_util import ClientMixinTest


class DisplayClientTest(ClientMixinTest):

	def test_display(self):
		with DisplayContext():
			from xpra.client.mixins import display
			def _DisplayClient():
				dc = display.DisplayClient()
				def get_root_size():
					return 1024, 768
				dc.get_root_size = get_root_size
				def get_screen_sizes(*_args):
					return ((1024, 768),)
				dc.get_screen_sizes = get_screen_sizes
				return dc
			opts = AdHocStruct()
			opts.desktop_fullscreen = False
			opts.desktop_scaling = False
			opts.dpi = 144
			with silence_info(display):
				self._test_mixin_class(_DisplayClient, opts, {
					"display" : ":999",
					"desktop_size" : (1024, 768),
					"max_desktop_size" : (3840, 2160),
					"actual_desktop_size" : (1024, 768),
					"resize_screen" : True,
					})

def main():
	unittest.main()


if __name__ == '__main__':
	main()
