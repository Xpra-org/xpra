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

from xpra.os_util import gi_import

Gdk = gi_import("Gdk")


def cursor_data(name: str, w=16, h=16, xhot=3, yhot=1) -> tuple:
    return "raw", 0, 0, w, h, xhot, yhot, 0x1234, b"\xff" * (w * h * 4), name


class TestCursors(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            raise unittest.SkipTest("no display")
        os.environ["XPRA_USE_LOCAL_CURSORS"] = "1"

    def make(self, name: str, xscale=1.0, yscale=1.0) -> tuple:
        """ the size and hotspot make_cursor() ends up using """
        from xpra.gtk.cursors import make_cursor
        made = []
        new_from_pixbuf = Gdk.Cursor.new_from_pixbuf

        def record(display, pixbuf, x, y):
            made.append((pixbuf.get_width(), pixbuf.get_height(), x, y))
            return new_from_pixbuf(display, pixbuf, x, y)

        Gdk.Cursor.new_from_pixbuf = record
        try:
            assert make_cursor(cursor_data(name), xscale, yscale)
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
        self.assertEqual((w, h), (pixbuf.get_width(), pixbuf.get_height()))
        self.assertEqual((str(x), str(y)), (pixbuf.get_option("x_hot"), pixbuf.get_option("y_hot")))

    def test_local_cursor_scaling(self):
        from xpra.gtk.cursors import get_local_cursor
        if not get_local_cursor("size_fdiag"):
            raise unittest.SkipTest("no cursor theme")
        w, h, x, y = self.make("size_fdiag")
        for scale in (2.0, 0.5):
            sw, sh, sx, sy = self.make("size_fdiag", scale, scale)
            self.assertEqual((sw, sh), (round(w * scale), round(h * scale)))
            self.assertEqual((sx, sy), (round(x * scale), round(y * scale)))

    def test_server_cursor(self):
        # no local cursor for this name: the server's image and hotspot are used as-is
        self.assertEqual(self.make("no-such-cursor-name"), (16, 16, 3, 1))


def main():
    unittest.main()


if __name__ == '__main__':
    main()
