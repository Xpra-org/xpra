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


class DisplayClientTest(ClientMixinTest):

	def test_display(self):
		if os.environ.get("DISPLAY") and POSIX and not OSX and os.environ.get("GDK_BACKEND", "x11")=="x11":
			from xpra.x11.gtk_x11.gdk_display_source import init_gdk_display_source
			init_gdk_display_source()
		from xpra.client.mixins.display import DisplayClient
		x = DisplayClient()
		def get_root_size():
			return 1024, 768
		x.get_root_size = get_root_size
		def get_screen_sizes(*_args):
			return ((1024, 768),)
		x.get_screen_sizes = get_screen_sizes
		opts = AdHocStruct()
		opts.desktop_fullscreen = False
		opts.desktop_scaling = False
		opts.dpi = 144
		x.init(opts)
		assert x.get_caps() is not None
		x.server_capabilities = typedict({
			"display" : ":999",
			"desktop_size" : (1024, 768),
			"max_desktop_size" : (3840, 2160),
			"actual_desktop_size" : (1024, 768),
			"resize_screen" : True,
			})
		x.parse_server_capabilities()

def main():
	unittest.main()


if __name__ == '__main__':
	main()
