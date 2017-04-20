# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#@PydevCodeAnalysisIgnore

from tests.wimpiggy import *
import struct
import sys
import gtk
import cairo

from tests.xpra.session.test import TestWithSession, assert_raises
import wimpiggy.prop as p
import wimpiggy.lowlevel
import wimpiggy.error

if sys.version < '3':
    import codecs
    def u(x):
        return codecs.unicode_escape_decode(x)[0]
else:
    def u(x):
        return x

class TestProp(TestWithSession):
    def setUp(self):
        super(TestProp, self).setUp()
        f = lambda: gtk.gdk.Window(self.display.get_default_screen().get_root_window(),
                                   width=10, height=10,
                                   window_type=gtk.gdk.WINDOW_TOPLEVEL,
                                   wclass=gtk.gdk.INPUT_OUTPUT,
                                   event_mask=0)
        self.win = f()
        self.win2 = f()

    def enc(self, t, value, exp):
        enc = p._prop_encode(self.display, t, value)
        assert enc[-1] == exp
        assert p._prop_decode(self.display, t, enc[-1]) == value
        p.prop_set(self.win, "__TEST__", t, value)
        assert p.prop_get(self.win, "__TEST__", t) == value

    def test_simple_enc_dec_set_get(self):
        gtk.gdk.flush()
        self.enc("utf8", u("\u1000"), "\xe1\x80\x80")
        self.enc(["utf8"], [u("a"), u("\u1000")], "a\x00\xe1\x80\x80")
        self.enc("latin1", u("\u00c2"), "\xc2")
        self.enc(["latin1"], [u("a"), u("\u00c2")], "a\x00\xc2")
        # These are X predefined atoms with fixed numeric values
        self.enc("atom", "PRIMARY", struct.pack("@I", 1))
        self.enc(["atom"], ["PRIMARY", "SECONDARY"], struct.pack("@II", 1, 2))
        self.enc("u32", 1, struct.pack("@I", 1))
        self.enc("u32", 0xffffffff, struct.pack("@I", 0xffffffff))
        self.enc(["u32"], [1, 2], struct.pack("@II", 1, 2))
        self.enc("window", self.win,
                 struct.pack("@I", wimpiggy.lowlevel.get_xwindow(self.win)))
        self.enc(["window"], [self.win, self.win2],
                 struct.pack("@II", *map(wimpiggy.lowlevel.get_xwindow,
                                         (self.win, self.win2))))

    def test_prop_get_set_errors(self):
        assert p.prop_get(self.win, "SADFSAFDSADFASDF", "utf8") is None
        self.win2.destroy()
        gtk.gdk.flush()
        assert_raises(wimpiggy.error.XError,
                      wimpiggy.error.trap.call,
                      p.prop_set, self.win2, "ASDF", "utf8", u(""))

        assert p.prop_get(self.win2, "ASDF", "utf8") is None
        p.prop_set(self.win, "ASDF", "utf8", u(""))
        assert p.prop_get(self.win, "ASDF", "latin1") is None

    def test_strut(self):
        p.prop_set(self.win,
                   "_NET_WM_STRUT_PARTIAL", "debug-CARDINAL",
                   struct.pack("@" + "i" * 12, *range(12)))
        partial = p.prop_get(self.win,
                             "_NET_WM_STRUT_PARTIAL", "strut-partial")
        assert partial.left == 0
        assert partial.right == 1
        assert partial.top == 2
        assert partial.bottom == 3
        assert partial.left_start_y == 4
        assert partial.left_end_y == 5
        assert partial.right_start_y == 6
        assert partial.right_end_y == 7
        assert partial.top_start_x == 8
        assert partial.top_end_x == 9
        assert partial.bottom_start_x == 10
        assert partial.bottom_stop_x == 11

        p.prop_set(self.win,
                   "_NET_WM_STRUT", "debug-CARDINAL",
                   struct.pack("@" + "i" * 4, *range(4)))
        full = p.prop_get(self.win,
                          "_NET_WM_STRUT", "strut")
        assert full.left == 0
        assert full.right == 1
        assert full.top == 2
        assert full.bottom == 3
        assert full.left_start_y == 0
        assert full.left_end_y == 0
        assert full.right_start_y == 0
        assert full.right_end_y == 0
        assert full.top_start_x == 0
        assert full.top_end_x == 0
        assert full.bottom_start_x == 0
        assert full.bottom_stop_x == 0

        p.prop_set(self.win,
                   "corrupted1", "debug-CARDINAL",
                   "\xff\xff\xff\xff")
        corrupted = p.prop_get(self.win,
                               "corrupted1", "strut")
        assert corrupted.left == 0xffffffff
        assert corrupted.right == 0
        assert corrupted.top == 0
        assert corrupted.bottom == 0
        assert corrupted.left_start_y == 0
        assert corrupted.left_end_y == 0
        assert corrupted.right_start_y == 0
        assert corrupted.right_end_y == 0
        assert corrupted.top_start_x == 0
        assert corrupted.top_end_x == 0
        assert corrupted.bottom_start_x == 0
        assert corrupted.bottom_stop_x == 0

    def _assert_icon_matches(self, prop, expected):
        surf = p.prop_get(self.win, prop, "icon")
        assert surf.get_width() == expected.get_width()
        assert surf.get_height() == expected.get_height()
        assert str(surf.get_data()) == str(expected.get_data())

    def test_icon(self):
        LARGE_W = 49
        LARGE_H = 47
        SMALL_W = 25
        SMALL_H = 23

        large = cairo.ImageSurface(cairo.FORMAT_ARGB32, LARGE_W, LARGE_H)
        # Scribble something on our "icon"
        large_cr = cairo.Context(large)
        pat = cairo.LinearGradient(0, 0, LARGE_W, LARGE_H)
        pat.add_color_stop_rgb(0, 1, 0, 0)
        pat.add_color_stop_rgb(1, 0, 1, 0)
        large_cr.set_source(pat)
        large_cr.paint()

        # Make a "small version"
        small = cairo.ImageSurface(cairo.FORMAT_ARGB32, SMALL_W, SMALL_H)
        small_cr = cairo.Context(small)
        small_cr.set_source(pat)
        small_cr.paint()

        small_dat = struct.pack("@II", SMALL_W, SMALL_H) + str(small.get_data())
        large_dat = struct.pack("@II", LARGE_W, LARGE_H) + str(large.get_data())

        icon_bytes = small_dat + large_dat + small_dat

        p.prop_set(self.win, "_NET_WM_ICON", "debug-CARDINAL", icon_bytes)
        self._assert_icon_matches("_NET_WM_ICON", large)

        # Corrupted icons:

        # Width, but not height:
        p.prop_set(self.win,
                   "corrupted1", "debug-CARDINAL",
                   "\xff\xff\xff\xff")
        corrupted1 = p.prop_get(self.win, "corrupted1", "icon")
        assert corrupted1 is None
        # Width and height, but not enough data for them:
        p.prop_set(self.win,
                   "corrupted2", "debug-CARDINAL",
                   struct.pack("@" + "i" * 4, 10, 10, 0, 0))
        corrupted2 = p.prop_get(self.win, "corrupted2", "icon")
        assert corrupted2 is None

        # A small, then a large, then a small, then a corrupted, should
        # successfully extract largest:
        p.prop_set(self.win,
                   "corrupted3", "debug-CARDINAL",
                   small_dat + large_dat + small_dat
                   # Width and height -- large enough to overflow to negative
                   # if we treat sizes as signed
                   + "\xff\xff\xff\xff" + "\xff\xff\xff\xff"
                   # Inadequate body
                   + "\xff\xff\xff\xff")
        self._assert_icon_matches("corrupted3", large)

    def test_multiple_conversion(self):
        x1 = wimpiggy.lowlevel.get_xatom("X1")
        x2 = wimpiggy.lowlevel.get_xatom("X2")
        x3 = wimpiggy.lowlevel.get_xatom("X3")
        x4 = wimpiggy.lowlevel.get_xatom("X4")
        p.prop_set(self.win, "_MY_MULTIPLE_TEST", "debug-CARDINAL",
                   struct.pack("@IIII", x1, x2, x3, x4))
        out = p.prop_get(self.win, "_MY_MULTIPLE_TEST",
                         ["multiple-conversion"])
        assert len(out) == 4
        assert out == ["X1", "X2", "X3", "X4"]

    # FIXME: WMSizeHints and WMHints tests.  Stupid baroque formats...
