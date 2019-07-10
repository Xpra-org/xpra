#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.os_util import POSIX
from xpra.util import AdHocStruct, typedict
from xpra.client.mixins.clipboard import ClipboardClient
from unit.client.mixins.clientmixintest_util import ClientMixinTest



class ClipboardClientTest(ClientMixinTest):

	def test_audio(self):
		x = ClipboardClient()
		opts = AdHocStruct()
		opts.clipboard = "yes"
		opts.clipboard_direction = "both"
		x.init(opts)
		from xpra.clipboard.clipboard_core import ALL_CLIPBOARDS
		assert x.get_caps() is not None
		x.server_capabilities = typedict({
			"clipboard" : True,
			"clipboard.enable-selections" : ALL_CLIPBOARDS,
			"clipboard.contents-slice-fix" : True,
			})
		x.parse_server_capabilities()
		if not POSIX:
			self.glib.timeout_add(5000, self.stop)
			x.process_ui_capabilities()
			self.main_loop.run()
			assert len(self.packets)>2

def main():
	unittest.main()


if __name__ == '__main__':
	main()
