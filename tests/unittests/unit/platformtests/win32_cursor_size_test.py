#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
The default cursor size a win32 client asks the server for:
`SM_CXCURSOR` follows the DPI, the "pointer size" setting is only in the registry.
These tests are skipped on non-Windows platforms.
"""

import sys
import unittest

WIN32 = sys.platform == "win32"


@unittest.skipUnless(WIN32, "the win32 platform code is only available on MS Windows")
class DefaultCursorSizeTest(unittest.TestCase):

    def size(self, base_size: int, cursor_metric: int) -> tuple[int, int]:
        from xpra.platform.win32 import gui
        get_cursor_base_size = gui._get_cursor_base_size
        GetSystemMetrics = gui.GetSystemMetrics
        gui._get_cursor_base_size = lambda: base_size
        gui.GetSystemMetrics = lambda _index: cursor_metric
        try:
            return gui.get_default_cursor_size()
        finally:
            gui._get_cursor_base_size = get_cursor_base_size
            gui.GetSystemMetrics = GetSystemMetrics

    def test_defaults(self):
        self.assertEqual(self.size(32, 32), (32, 32))

    def test_dpi(self):
        # 150%:
        self.assertEqual(self.size(32, 48), (48, 48))

    def test_pointer_size(self):
        self.assertEqual(self.size(112, 32), (112, 112))

    def test_pointer_size_and_dpi(self):
        self.assertEqual(self.size(112, 48), (168, 168))
        # the largest pointer at 125%:
        self.assertEqual(self.size(256, 40), (320, 320))

    def test_no_pointer_size(self):
        # older versions don't have the setting:
        self.assertEqual(self.size(0, 48), (48, 48))

    def test_registry(self):
        from xpra.platform.win32.gui import _get_cursor_base_size
        base_size = _get_cursor_base_size()
        # whatever the setting is, or 0 without one:
        self.assertIsInstance(base_size, int)
        self.assertGreaterEqual(base_size, 0)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
