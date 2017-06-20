#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unit.client.x11_clipboard_test_util import X11ClipboardTestUtil
from xpra.os_util import OSX, POSIX, PYTHON2


class OSXLikeClipboardTest(X11ClipboardTestUtil):

	@classmethod
	def get_run_env(cls):
		env = X11ClipboardTestUtil.get_run_env()
		env.update({
					"XPRA_CLIPBOARD_WANT_TARGETS"	: "1",
					"XPRA_CLIPBOARD_GREEDY"			: "1",
					})
		return env


	def test_copy(self):
		self.do_test_copy()

	def test_disabled(self):
		self.do_test_copy("disabled")

	def test_to_server(self):
		self.do_test_copy("to-server")

	def test_to_client(self):
		self.do_test_copy("to-client")



def main():
	if POSIX and PYTHON2 and not OSX:
		unittest.main()


if __name__ == '__main__':
	main()
