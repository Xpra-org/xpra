#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Verify the native window frame geometry."""

import unittest

from xpra.os_util import WIN32


@unittest.skipUnless(WIN32, "the win32 client is only available on MS Windows")
class Win32WindowGeometryTest(unittest.TestCase):

    def test_system_geometry_large_coordinates(self) -> None:
        import win32con
        from xpra.client.win32.window import system_geometry
        # beyond the 16-bit range: the frame must still surround the client area
        for x, y in ((40000, 50000), (-40000, -50000), (100, 100)):
            with self.subTest(x=x, y=y):
                wx, wy, ww, wh = system_geometry(x, y, 640, 480, win32con.WS_OVERLAPPEDWINDOW, 0)
                self.assertTrue(x - 64 < wx <= x and y - 128 < wy <= y, (wx, wy))
                self.assertTrue(wx + ww >= x + 640 and wy + wh >= y + 480, (ww, wh))


if __name__ == "__main__":
    unittest.main()
