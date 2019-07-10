#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct, typedict
from xpra.client.mixins.tray import TrayClient
from unit.client.mixins.clientmixintest_util import ClientMixinTest


class AudioClientTest(ClientMixinTest):

	def test_audio(self):
		x = TrayClient()
		def get_tray_menu_helper_class():
			return None
		def timeout_add(*_args):
			return None
		x.get_tray_menu_helper_class = get_tray_menu_helper_class
		x.timeout_add = timeout_add
		self.mixin = x
		opts = AdHocStruct()
		opts.tray = True
		opts.delay_tray = 0
		opts.tray_icon = ""
		x.init(opts)
		assert x.get_caps() is not None

def main():
	unittest.main()


if __name__ == '__main__':
	main()
