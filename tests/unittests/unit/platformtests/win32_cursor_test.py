#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Tests for the cursors of the native win32 client:
the cursors are drawn with `DrawIconEx` and read back, so we check what Windows
actually does with them rather than how we built them.
These tests are skipped on non-Windows platforms.
"""

import sys
import unittest
from ctypes import sizeof, byref, c_void_p, string_at, memmove

WIN32 = sys.platform == "win32"

RED = (255, 0, 0, 255)
BLUE = (0, 0, 255, 255)
CLEAR = (0, 0, 0, 0)
# the canvas the cursors are drawn on, in `BGRA` order:
WHITE = (255, 255, 255)


def rgba(w: int, h: int, pixel=RED, right_half=None) -> bytes:
    """ `RGBA` pixels, optionally with a different right half """
    row = bytes(pixel) * (w // 2) + bytes(right_half or pixel) * (w - w // 2)
    return row * h


def cursor_data(w: int, h: int, xhot: int, yhot: int, pixels: bytes, serial=0x1234) -> tuple:
    return "raw", 0, 0, w, h, xhot, yhot, serial, pixels, "test-cursor"


def draw(hcursor: int, width=128, height=128) -> list[tuple[int, int, int]]:
    """ draw the cursor at its own size on a white canvas and return the `BGR` pixels """
    import win32con
    from xpra.platform.win32.common import (
        BITMAPV5HEADER, CreateDIBSection, CreateCompatibleDC, SelectObject, DeleteObject, DeleteDC, DrawIconEx,
    )
    header = BITMAPV5HEADER()
    header.bV5Size = sizeof(BITMAPV5HEADER)
    header.bV5Width = width
    header.bV5Height = -height
    header.bV5Planes = 1
    header.bV5BitCount = 32
    header.bV5Compression = win32con.BI_RGB
    bits = c_void_p()
    hdc = CreateCompatibleDC(None)
    bitmap = CreateDIBSection(hdc, byref(header), win32con.DIB_RGB_COLORS, byref(bits), None, 0)
    old = SelectObject(hdc, bitmap)
    try:
        size = width * height * 4
        memmove(bits, b"\xff" * size, size)
        # a size of zero without `DI_DEFAULTSIZE` draws the cursor at its own size:
        assert DrawIconEx(hdc, 0, 0, hcursor, 0, 0, 0, None, win32con.DI_NORMAL)
        data = string_at(bits, size)
    finally:
        SelectObject(hdc, old)
        DeleteObject(bitmap)
        DeleteDC(hdc)
    return [tuple(data[i:i + 3]) for i in range(0, size, 4)]


def region(pixels: list, x: int, y: int, w: int, h: int, width=128) -> set:
    return {pixels[row * width + col] for row in range(y, y + h) for col in range(x, x + w)}


def hotspot(hcursor: int) -> tuple[int, int]:
    from xpra.platform.win32.common import GetIconInfo, ICONINFO, DeleteObject
    info = ICONINFO()
    assert GetIconInfo(hcursor, byref(info))
    for bitmap in (info.hbmColor, info.hbmMask):
        if bitmap:
            DeleteObject(bitmap)
    return info.xHotspot, info.yHotspot


@unittest.skipUnless(WIN32, "the win32 client is only available on MS Windows")
class HCursorTest(unittest.TestCase):

    def setUp(self):
        self.hcursors = []

    def tearDown(self):
        from xpra.platform.win32.common import DestroyCursor
        for hcursor in self.hcursors:
            DestroyCursor(hcursor)

    def make(self, w: int, h: int, xhot: int, yhot: int, pixels: bytes) -> int:
        from xpra.client.win32.cursor import make_hcursor
        hcursor = make_hcursor(w, h, xhot, yhot, pixels)
        self.assertTrue(hcursor)
        self.hcursors.append(hcursor)
        return hcursor

    def test_full_size(self):
        # bigger than the 32x32 system cursors, and not square:
        hcursor = self.make(64, 96, 40, 90, rgba(64, 96))
        pixels = draw(hcursor)
        # `RGBA` red is `BGR` (0, 0, 255):
        self.assertEqual(region(pixels, 0, 0, 64, 96), {(0, 0, 255)})
        self.assertEqual(region(pixels, 64, 0, 64, 128), {WHITE})
        self.assertEqual(region(pixels, 0, 96, 64, 32), {WHITE})
        self.assertEqual(hotspot(hcursor), (40, 90))

    def test_alpha(self):
        hcursor = self.make(16, 16, 0, 0, rgba(16, 16, BLUE, CLEAR))
        pixels = draw(hcursor)
        self.assertEqual(region(pixels, 0, 0, 8, 16), {(255, 0, 0)})
        self.assertEqual(region(pixels, 8, 0, 8, 16), {WHITE})

    def test_invisible(self):
        # without a single opaque pixel, Windows uses the mask instead of the alpha channel:
        hcursor = self.make(16, 16, 0, 0, rgba(16, 16, CLEAR))
        self.assertEqual(region(draw(hcursor), 0, 0, 16, 16), {WHITE})

    def test_odd_size(self):
        # the rows of the mask are word aligned:
        hcursor = self.make(17, 5, 16, 4, rgba(17, 5, CLEAR))
        self.assertEqual(region(draw(hcursor), 0, 0, 17, 5), {WHITE})
        self.assertEqual(hotspot(hcursor), (16, 4))

    def test_hotspot_clamped(self):
        hcursor = self.make(8, 8, 20, 30, rgba(8, 8))
        self.assertEqual(hotspot(hcursor), (7, 7))


@unittest.skipUnless(WIN32, "the win32 client is only available on MS Windows")
class Win32CursorsTest(unittest.TestCase):

    def setUp(self):
        from xpra.client.win32.cursor import Win32Cursors
        self.cursors = Win32Cursors()

    def tearDown(self):
        self.cursors.cleanup()

    def test_scaling(self):
        hcursor = self.cursors.get_hcursor(cursor_data(16, 8, 4, 6, rgba(16, 8)), 2, 3)
        pixels = draw(hcursor)
        self.assertEqual(region(pixels, 0, 0, 32, 24), {(0, 0, 255)})
        self.assertEqual(region(pixels, 32, 0, 1, 24), {WHITE})
        self.assertEqual(region(pixels, 0, 24, 32, 1), {WHITE})
        self.assertEqual(hotspot(hcursor), (8, 18))

    def test_shared(self):
        pixels = rgba(16, 16)
        hcursor = self.cursors.get_hcursor(cursor_data(16, 16, 1, 1, pixels))
        # the same cursor, from another packet:
        self.assertEqual(self.cursors.get_hcursor(cursor_data(16, 16, 1, 1, bytearray(pixels))), hcursor)
        # but not at another scale, or with another image:
        self.assertNotEqual(self.cursors.get_hcursor(cursor_data(16, 16, 1, 1, pixels), 2, 2), hcursor)
        self.assertNotEqual(self.cursors.get_hcursor(cursor_data(16, 16, 1, 1, rgba(16, 16, BLUE))), hcursor)
        self.assertEqual(len(self.cursors.hcursors), 3)

    def test_free_unused(self):
        from xpra.platform.win32.common import GetIconInfo, ICONINFO
        used = self.cursors.get_hcursor(cursor_data(16, 16, 1, 1, rgba(16, 16)))
        unused = self.cursors.get_hcursor(cursor_data(16, 16, 1, 1, rgba(16, 16, BLUE)))
        self.cursors.free_unused((used, 0))
        self.assertEqual(tuple(self.cursors.hcursors.values()), (used, ))
        self.assertEqual(hotspot(used), (1, 1))
        # the handle is no longer valid:
        self.assertFalse(GetIconInfo(unused, byref(ICONINFO())))

    def test_invalid(self):
        for data in (
            cursor_data(16, 16, 0, 0, b"\xff" * 16),
            cursor_data(0, 16, 0, 0, b""),
            ("png", 0, 0, 16, 16, 0, 0, 1, rgba(16, 16), ""),
            ("raw", 0, 0),
        ):
            self.assertEqual(self.cursors.get_hcursor(data), 0)
        self.assertFalse(self.cursors.hcursors)


class FakeWindowManager:
    def __init__(self):
        self.windows = {}

    def get_window(self, wid: int):
        return self.windows.get(wid)


class FakeClient:

    def __init__(self):
        from xpra.client.win32.cursor import Win32Cursors
        self.hcursors = Win32Cursors()
        self.window_manager = FakeWindowManager()
        self.subsystems = {"window": self.window_manager}

    def get_subsystem(self, name: str):
        return self.subsystems.get(name)

    def get_windows(self) -> tuple:
        return tuple(self.window_manager.windows.values())


@unittest.skipUnless(WIN32, "the win32 client is only available on MS Windows")
class WindowCursorTest(unittest.TestCase):

    def setUp(self):
        self.client = FakeClient()
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            window.destroy()
            # this is normally done from the main loop, which we don't run:
            window.cleanup_class()
        self.client.hcursors.cleanup()

    def make_window(self, wid=1):
        from xpra.util.objects import typedict
        from xpra.client.win32.window import ClientWindow
        window = ClientWindow(self.client, None, wid, (100, 100, 200, 100), (200, 100), typedict(),
                              False, {}, None, (4096, 4096), 32, None)
        window.create()
        self.windows.append(window)
        self.client.window_manager.windows[wid] = window
        return window

    def set_windows_cursor(self, windows, data) -> None:
        from xpra.client.win32.client import XpraWin32Client
        XpraWin32Client.set_windows_cursor(self.client, windows, data)

    def set_cursor_message(self, window, hit_test: int) -> int:
        import win32con
        from xpra.platform.win32.common import SendMessageW
        return SendMessageW(window.hwnd, win32con.WM_SETCURSOR, window.hwnd, hit_test | (win32con.WM_MOUSEMOVE << 16))

    def test_set_cursor_message(self):
        import win32con
        from xpra.platform.win32.common import GetCursor, SetCursor, LoadCursor
        window = self.make_window()
        self.set_windows_cursor([window], cursor_data(16, 16, 1, 1, rgba(16, 16)))
        self.assertTrue(window.hcursor)
        SetCursor(0)
        self.assertEqual(self.set_cursor_message(window, win32con.HTCLIENT), 1)
        self.assertEqual(GetCursor(), window.hcursor)
        # the borders keep their resize cursors:
        self.set_cursor_message(window, win32con.HTLEFT)
        self.assertEqual(GetCursor(), LoadCursor(0, win32con.IDC_SIZEWE))
        # back to the default cursor:
        self.set_windows_cursor([window], ())
        self.assertEqual(window.hcursor, 0)
        SetCursor(0)
        # handled by `DefWindowProcW`, using the cursor of the window class:
        self.set_cursor_message(window, win32con.HTCLIENT)
        self.assertEqual(GetCursor(), LoadCursor(0, win32con.IDC_ARROW))
        # and the cursor it no longer uses is gone:
        self.assertFalse(self.client.hcursors.hcursors)

    def test_shared_between_windows(self):
        windows = [self.make_window(wid) for wid in (1, 2)]
        data = cursor_data(16, 16, 1, 1, rgba(16, 16))
        self.set_windows_cursor(windows, data)
        hcursor = windows[0].hcursor
        self.assertTrue(hcursor)
        self.assertEqual(windows[1].hcursor, hcursor)
        # re-applying the same cursor to one of them does not create another one:
        self.set_windows_cursor(windows[1:], cursor_data(16, 16, 1, 1, rgba(16, 16), serial=0x5678))
        self.assertEqual(windows[1].hcursor, hcursor)
        # a new cursor for one window only, the other one still uses the first cursor:
        self.set_windows_cursor(windows[1:], cursor_data(16, 16, 1, 1, rgba(16, 16, BLUE)))
        self.assertNotEqual(windows[1].hcursor, hcursor)
        self.assertEqual(set(self.client.hcursors.hcursors.values()), {hcursor, windows[1].hcursor})
        # once the window is gone, so is its cursor:
        windows[0].destroy()
        del self.client.window_manager.windows[1]
        self.set_windows_cursor(windows[1:], cursor_data(16, 16, 1, 1, rgba(16, 16, BLUE)))
        self.assertEqual(tuple(self.client.hcursors.hcursors.values()), (windows[1].hcursor, ))


def main():
    unittest.main()


if __name__ == "__main__":
    main()
