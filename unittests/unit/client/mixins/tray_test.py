#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.os_util import OSX
from xpra.util import AdHocStruct
from xpra.client.mixins.tray import TrayClient
from unit.client.mixins.clientmixintest_util import ClientMixinTest


class AudioClientTest(ClientMixinTest):

	def test_tray(self):
		def _TrayClient():
			x = TrayClient()
			if OSX:
				def noop(*_args):
					return
				x.after_handshake = noop
			def get_tray_menu_helper_class():
				return None
			x.get_tray_menu_helper_class = get_tray_menu_helper_class
			return x
		opts = AdHocStruct()
		opts.tray = True
		opts.delay_tray = 0
		opts.tray_icon = ""
		self._test_mixin_class(_TrayClient, opts)

def main():
	unittest.main()


if __name__ == '__main__':
	main()
