#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.objects import AdHocStruct
from unit.client.subsystem.clientmixintest_util import ClientMixinTest
from unit.process_test_util import DisplayContext


class ClipboardClientTest(ClientMixinTest):

	def test_clipboard(self):
		from xpra.client.subsystem.clipboard import ClipboardClient
		opts = AdHocStruct()
		opts.clipboard = "yes"
		opts.clipboard_direction = "both"
		opts.local_clipboard = "CLIPBOARD"
		opts.remote_clipboard = "CLIPBOARD"
		self._test_mixin_class(ClipboardClient, opts, {
			"clipboard" : True,
			"clipboard.enable-selections" : True,
			"clipboard.contents-slice-fix" : True,
			})
		self.glib.timeout_add(5000, self.stop)
		self.main_loop.run()
		assert len(self.packets)>=1
		assert self.packets[0][0]=="clipboard-enable-selections"

def main():
	with DisplayContext():
		unittest.main()


if __name__ == '__main__':
	main()
