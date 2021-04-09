#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.client.window_border import WindowBorder


class AuthHandlersTest(unittest.TestCase):

	def test_toggle(self):
		b = WindowBorder(shown=True)
		b.toggle()
		assert b.shown is False

	def test_clone(self):
		b = WindowBorder(red=1, blue=0, green=1, alpha=0.5, size=10)
		b2 = b.clone()
		assert b.red==b2.red
		assert b.blue==b2.blue
		assert b.green==b2.green
		assert b.alpha==b2.alpha
		assert b.size==b2.size

	def test_repr(self):
		b = WindowBorder(red=0, blue=1, green=0.5)
		assert repr(b).find("00")>=0
		assert repr(b).find("FF")>=0


def main():
	unittest.main()


if __name__ == '__main__':
	main()
