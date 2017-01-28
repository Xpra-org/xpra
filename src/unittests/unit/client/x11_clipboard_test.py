#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import unittest

from unit.client.x11_clipboard_test_util import X11ClipboardTestUtil
from xpra.os_util import OSX

from xpra.log import Logger
log = Logger("clipboard")


class X11ClipboardTest(X11ClipboardTestUtil):

	@classmethod
	def setUpClass(cls):
		super(X11ClipboardTest, cls).setUpClass()
		X11ClipboardTest.default_xpra_args += ["--speaker=no", "--microphone=no", "-d clipboard"]

	def test_copy(self):
		self.do_test_copy()

	def test_disabled(self):
		self.do_test_copy("disabled")

	def test_to_server(self):
		self.do_test_copy("to-server")

	def test_to_client(self):
		self.do_test_copy("to-client")



def main():
	if os.name=="posix" and sys.version_info[0]==2 and not OSX:
		unittest.main()


if __name__ == '__main__':
	main()
