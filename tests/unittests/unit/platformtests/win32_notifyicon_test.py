#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
The win32 system tray icon and its balloon notifications use `Shell_NotifyIconW`,
so the text must fit in the `WCHAR` buffers of `NOTIFYICONDATAW`,
and the structure must have the exact size the shell expects,
otherwise it silently ignores the fields it does not expect for that size.
These tests are skipped on non-Windows platforms.
"""

import sys
import unittest
from ctypes import sizeof, c_void_p

WIN32 = sys.platform == "win32"

# the 64 and 32-bit sizes of NOTIFYICONDATAW from the Windows SDK:
NOTIFYICONDATAW_SIZE = {8: 976, 4: 956}

# a character outside the BMP, which uses two WCHARs:
SMILE = "\U0001f600"
# "Chinese title", as in #5104:
CHINESE = "中文標題"


@unittest.skipUnless(WIN32, "the win32 platform code is only available on MS Windows")
class NotifyIconDataTest(unittest.TestCase):

    def test_layout(self):
        from xpra.platform.win32.NotifyIcon import NOTIFYICONDATA, NOTIFYICONDATAW
        self.assertIs(NOTIFYICONDATA, NOTIFYICONDATAW)
        self.assertEqual(sizeof(NOTIFYICONDATAW), NOTIFYICONDATAW_SIZE[sizeof(c_void_p)])

    def test_truncate_wchars(self):
        from xpra.platform.win32.NotifyIcon import truncate_wchars
        self.assertEqual(truncate_wchars("", 4), "")
        self.assertEqual(truncate_wchars("abc", 3), "abc")
        self.assertEqual(truncate_wchars("abcd", 3), "abc")
        self.assertEqual(truncate_wchars(CHINESE, 4), CHINESE[:4])
        # the surrogate pair is not split:
        self.assertEqual(truncate_wchars("ab" + SMILE, 3), "ab")
        self.assertEqual(truncate_wchars("ab" + SMILE, 4), "ab" + SMILE)

    def test_chop_string(self):
        from xpra.platform.win32.balloon import chop_string
        self.assertEqual(chop_string("", 63), "")
        self.assertEqual(chop_string(CHINESE, 63), CHINESE)
        self.assertEqual(chop_string("a\r\nb", 63), "ab")
        self.assertEqual(chop_string("a\r\nb", 63, False), "a\r\nb")
        self.assertEqual(chop_string("abcdef", 4), "abc…")
        self.assertEqual(chop_string("ab" + SMILE + "cd", 4), "ab…")

    def test_fits(self):
        from xpra.platform.win32.NotifyIcon import NOTIFYICONDATA, MAX_TIP_SIZE, truncate_wchars
        from xpra.platform.win32.balloon import chop_string
        nid = NOTIFYICONDATA()
        for text in (CHINESE * 100, SMILE * 300, "x" + SMILE * 300):
            nid.szInfo = chop_string(text, 255, False)
            nid.szInfoTitle = chop_string(text, 63)
            nid.szTip = truncate_wchars(text, MAX_TIP_SIZE - 1)
            self.assertTrue(nid.szInfoTitle.endswith("…"))
            self.assertTrue(text.startswith(nid.szTip))

    def test_unicode_round_trip(self):
        from xpra.platform.win32.NotifyIcon import NOTIFYICONDATA
        nid = NOTIFYICONDATA()
        nid.szInfoTitle = CHINESE
        nid.szInfo = SMILE
        self.assertEqual(nid.szInfoTitle, CHINESE)
        self.assertEqual(nid.szInfo, SMILE)


def has_taskbar() -> bool:
    if not WIN32:
        return False
    from xpra.platform.win32.common import FindWindowA
    return bool(FindWindowA(b"Shell_TrayWnd", None))


@unittest.skipUnless(has_taskbar(), "requires the MS Windows taskbar")
class NotifyIconTest(unittest.TestCase):

    def make_icon(self, app_id: int, title: str):
        from xpra.platform.win32.NotifyIcon import win32NotifyIcon
        from xpra.platform.win32.common import DestroyWindow
        icon = win32NotifyIcon(app_id, title)

        def cleanup() -> None:
            icon.destroy()
            DestroyWindow(icon.hwnd)
        self.addCleanup(cleanup)
        return icon

    def find(self, icon) -> bool:
        from ctypes import byref
        from ctypes.wintypes import RECT
        from xpra.platform.win32.NotifyIcon import NOTIFYICONIDENTIFIER, Shell_NotifyIconGetRect
        nii = NOTIFYICONIDENTIFIER()
        nii.cbSize = sizeof(NOTIFYICONIDENTIFIER)
        nii.hWnd = icon.hwnd
        nii.uID = icon.app_id
        rect = RECT()
        try:
            return Shell_NotifyIconGetRect(byref(nii), byref(rect)) == 0
        except OSError:
            return False

    def test_unicode_tooltip(self):
        icon = self.make_icon(0x5104, CHINESE)
        self.assertTrue(self.find(icon))
        icon.set_tooltip(SMILE * 100)

    def test_multiple_icons(self):
        # ie: two clients, which would collide if the icons were registered with a GUID
        icon1 = self.make_icon(0x5104, "one")
        icon2 = self.make_icon(0x5105, "two")
        self.assertTrue(self.find(icon1))
        self.assertTrue(self.find(icon2))


def main():
    unittest.main()


if __name__ == '__main__':
    main()
