#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.client.paint_colors import get_default_paint_box_color, get_paint_box_color, BLACK


class PaintColorsTest(unittest.TestCase):
	def test_defaults(self):
		assert get_default_paint_box_color()==BLACK
		assert get_paint_box_color("invalid-value")==BLACK
		for encoding in ("png", "h264"):
			assert get_paint_box_color(encoding)!=BLACK

def main():
	unittest.main()


if __name__ == '__main__':
	main()
