#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
The servers send x11 cursor names, which the local theme may not have.
When we do find a local cursor, its image replaces the one from the server
and it must still go through the same scaling as any other cursor.
"""

import os
import unittest

from xpra.os_util import gi_import, WIN32

Gdk = gi_import("Gdk")


def cursor_data(name: str, w=16, h=16, xhot=3, yhot=1) -> tuple:
    return "raw", 0, 0, w, h, xhot, yhot, 0x1234, b"\xff" * (w * h * 4), name


# what the tests pretend the size of the system cursors is:
SYSTEM_CURSOR_SIZE = (48, 48)


def made(w: int, h: int, x: int, y: int) -> tuple:
    """
    The cursor we expect to hand to GDK: on win32, it is padded to a square
    at least as big as the system cursors.
    """
    if WIN32:
        w = h = max(w, h, *SYSTEM_CURSOR_SIZE)
    return w, h, x, y


class TestCursors(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not WIN32 and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            raise unittest.SkipTest("no display")
        os.environ["XPRA_USE_LOCAL_CURSORS"] = "1"

    def setUp(self):
        import xpra.platform.gui as platform_gui
        self.get_default_cursor_size = platform_gui.get_default_cursor_size
        platform_gui.get_default_cursor_size = lambda: SYSTEM_CURSOR_SIZE

    def tearDown(self):
        import xpra.platform.gui as platform_gui
        platform_gui.get_default_cursor_size = self.get_default_cursor_size

    def make(self, name: str, xscale=1.0, yscale=1.0, **kwargs) -> tuple:
        """ the size and hotspot make_cursor() ends up using """
        from xpra.gtk.cursors import make_cursor
        made = []
        new_from_pixbuf = Gdk.Cursor.new_from_pixbuf

        def record(display, pixbuf, x, y):
            made.append((pixbuf.get_width(), pixbuf.get_height(), x, y))
            return new_from_pixbuf(display, pixbuf, x, y)

        Gdk.Cursor.new_from_pixbuf = record
        try:
            assert make_cursor(cursor_data(name, **kwargs), xscale, yscale)
        finally:
            Gdk.Cursor.new_from_pixbuf = new_from_pixbuf
        assert made, f"no cursor created for {name!r}"
        return made[-1]

    def test_aliases(self):
        from xpra.gtk.cursors import get_local_cursor
        if not get_local_cursor("left_ptr"):
            raise unittest.SkipTest("no cursor theme")
        for name in ("size_fdiag", "size_bdiag", "size_ver", "size_hor"):
            # these have no css name and no `Gdk.CursorType`, only aliases:
            assert get_local_cursor(name), f"no local cursor found for {name!r}"
        assert get_local_cursor("no-such-cursor-name") is None

    def test_local_cursor_hotspot(self):
        from xpra.gtk.cursors import get_local_cursor
        pixbuf = get_local_cursor("size_fdiag")
        if not pixbuf:
            raise unittest.SkipTest("no cursor theme")
        w, h, x, y = self.make("size_fdiag")
        # the local image is used, with the hotspot of the local image
        # and not the one the server sent for its own:
        self.assertEqual((w, h), made(pixbuf.get_width(), pixbuf.get_height(), x, y)[:2])
        self.assertEqual((str(x), str(y)), (pixbuf.get_option("x_hot"), pixbuf.get_option("y_hot")))

    def test_local_cursor_scaling(self):
        from xpra.gtk.cursors import get_local_cursor
        pixbuf = get_local_cursor("size_fdiag")
        if not pixbuf:
            raise unittest.SkipTest("no cursor theme")
        w, h = pixbuf.get_width(), pixbuf.get_height()
        x, y = self.make("size_fdiag")[2:]
        for scale in (2.0, 0.5):
            expected = made(round(w * scale), round(h * scale), round(x * scale), round(y * scale))
            self.assertEqual(self.make("size_fdiag", scale, scale), expected)

    def test_server_cursor(self):
        # no local cursor for this name: the server's image and hotspot are used as-is
        self.assertEqual(self.make("no-such-cursor-name"), made(16, 16, 3, 1))

    def test_large_cursor(self):
        # bigger than the system cursors (32x32 on win32) and not square:
        self.assertEqual(self.make("no-such-cursor-name", w=64, h=96, xhot=40, yhot=90), made(64, 96, 40, 90))

    def test_win32_hotspot(self):
        if not WIN32:
            raise unittest.SkipTest("win32 only")
        from xpra.gtk.cursors import make_cursor
        for w, h, xhot, yhot in ((64, 96, 40, 90), (96, 64, 90, 40), (16, 16, 3, 1)):
            cursor = make_cursor(cursor_data("no-such-cursor-name", w, h, xhot, yhot))
            # read back what GDK gave to win32:
            surface, x, y = cursor.get_surface()
            self.assertEqual((x, y), (xhot, yhot))
            # square, and at least as big as the system cursors:
            self.assertEqual((surface.get_width(), surface.get_height()), made(w, h, x, y)[:2])
            stride = surface.get_stride()
            pixels = surface.get_data()
            opaque = [(px, py) for py in range(surface.get_height()) for px in range(surface.get_width())
                      if pixels[py * stride + px * 4 + 3]]
            # the image must be where the hotspot expects it, and the rest is transparent:
            self.assertEqual((min(opaque), max(opaque)), ((0, 0), (w - 1, h - 1)), f"for {w}x{h} cursor")

    def test_max_size(self):
        import xpra.platform.gui as platform_gui
        get_max_cursor_size = platform_gui.get_max_cursor_size
        get_maximal_cursor_size = Gdk.Display.get_maximal_cursor_size

        def make_limited(gdk_max, scale, platform_max=(-1, -1), **kwargs) -> tuple:
            platform_gui.get_max_cursor_size = lambda: platform_max
            Gdk.Display.get_maximal_cursor_size = lambda _display: gdk_max
            try:
                return self.make("no-such-cursor-name", scale, scale, **kwargs)
            finally:
                platform_gui.get_max_cursor_size = get_max_cursor_size
                Gdk.Display.get_maximal_cursor_size = get_maximal_cursor_size

        # scaled up to 64x64 then shrunk back to the 32x32 limit, hotspot included:
        self.assertEqual(make_limited((32, 32), 4), made(32, 32, 6, 2))
        # both axes shrink by the same ratio, even when only one of them is too big:
        tall = {"w": 8, "h": 16, "xhot": 3, "yhot": 15}
        self.assertEqual(make_limited((32, 32), 4, **tall), made(16, 32, 6, 30))
        # no limit on one axis:
        self.assertEqual(make_limited((0, 32), 4, **tall), made(16, 32, 6, 30))
        # the platform limit replaces the one from GDK:
        self.assertEqual(make_limited((32, 32), 4, platform_max=(48, 48)), made(48, 48, 9, 3))
        # and on win32, there is no real limit:
        if WIN32:
            self.assertEqual(make_limited((32, 32), 4, platform_max=get_max_cursor_size()), made(64, 64, 12, 4))


def main():
    unittest.main()


if __name__ == '__main__':
    main()
