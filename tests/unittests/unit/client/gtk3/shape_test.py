#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gc
import unittest
from unittest.mock import MagicMock, patch

from cairo import RectangleInt, Region  # pylint: disable=no-name-in-module

from xpra.os_util import OSX, POSIX, gi_import
from xpra.client.gtk3.window.shape import ShapeWindow

# the shape data a server sends for a window which only has a bounding shape:
# the X server reports `Clip` as the full window rectangle when it isn't shaped,
# so applying it as a bounding shape would undo the `Bounding` shape
SIZE = (400, 400)
SHAPE = {
    "x": 10,
    "y": 20,
    "Bounding.rectangles": [(0, 0, 150, 100)],
    "Clip.rectangles": [(0, 0, 400, 400)],
    "ShapeInput.rectangles": [(0, 0, 50, 50)],
}


def make_region(rectangles) -> Region:
    region = Region()
    for rect in rectangles:
        region.union(RectangleInt(*rect))
    return region


def no_x11_bindings():
    return patch("xpra.client.gtk3.window.base.HAS_X11_BINDINGS", False)


class FakeBorder:
    shown = False
    size = 0


class ShapeTestWindow(ShapeWindow):
    """ just enough of a client window to exercise the shape subsystem """

    def __init__(self, gdk_window=None, scale=1):
        self._xscale = self._yscale = scale
        self._size = SIZE
        self.border = FakeBorder()
        self.gdk_window = gdk_window or MagicMock()
        self.realized: list[str] = []

    def get_window(self):
        return self.gdk_window

    def when_realized(self, ident: str, callback, *args) -> None:
        self.realized.append(ident)
        callback(*args)

    def sx(self, v: int) -> int:
        return round(v * self._xscale)

    def sy(self, v: int) -> int:
        return round(v * self._yscale)

    def srect(self, x: int, y: int, w: int, h: int) -> tuple[int, int, int, int]:
        return self.sx(x), self.sy(y), self.sx(w), self.sy(h)


class ShapeWindowTest(unittest.TestCase):

    def test_empty_shape_is_ignored(self) -> None:
        window = ShapeTestWindow()
        window.set_shape({})
        self.assertEqual(window.realized, [])
        with no_x11_bindings():
            window.set_shape(SHAPE)
        self.assertEqual(window.realized, ["shape"])

    def test_gdk_skips_the_clip_shape(self) -> None:
        with no_x11_bindings():
            kinds = ShapeTestWindow().get_shape_kinds()
        self.assertEqual(tuple(name for _, name in kinds), ("Bounding", "ShapeInput"))

    def test_x11_uses_all_the_shape_kinds(self) -> None:
        try:
            from xpra.x11.bindings.shape import SHAPE_KIND
        except ImportError as e:
            raise unittest.SkipTest(f"no X11 shape bindings: {e}")
        with patch("xpra.client.gtk3.window.base.HAS_X11_BINDINGS", True):
            kinds = ShapeTestWindow().get_shape_kinds()
        self.assertEqual(kinds, tuple(SHAPE_KIND.items()))

    def test_gdk_shape_calls(self) -> None:
        window = ShapeTestWindow()
        with no_x11_bindings():
            window.set_shape(SHAPE)
        gdk_window = window.gdk_window
        # the bounding shape is applied, and `Clip` is not:
        gdk_window.shape_combine_region.assert_called_once()
        region, x_off, y_off = gdk_window.shape_combine_region.call_args[0]
        self.assertEqual((x_off, y_off), (10, 20))
        self.assertTrue(region.equal(make_region(SHAPE["Bounding.rectangles"])))
        # gdk only applies the bounding shape when it processes an update:
        gdk_window.invalidate_rect.assert_called_once_with(None, True)
        # the input shape uses the input shape api:
        gdk_window.input_shape_combine_region.assert_called_once()
        region, x_off, y_off = gdk_window.input_shape_combine_region.call_args[0]
        self.assertEqual((x_off, y_off), (10, 20))
        self.assertTrue(region.equal(make_region(SHAPE["ShapeInput.rectangles"])))

    def test_offsets_are_scaled_just_once(self) -> None:
        window = ShapeTestWindow(scale=2)
        with no_x11_bindings():
            window.set_shape(SHAPE)
        gdk_window = window.gdk_window
        # every shape kind must use the same offsets,
        # scaling them once per kind would compound the scaling factor:
        for call_args in (
            gdk_window.shape_combine_region.call_args,
            gdk_window.input_shape_combine_region.call_args,
        ):
            self.assertEqual(call_args[0][1:], (20, 40))
        region = gdk_window.shape_combine_region.call_args[0][0]
        self.assertTrue(region.equal(make_region([(0, 0, 300, 200)])))


class GDKShapeDisplayTest(unittest.TestCase):
    """ verify that the gdk fallback really does shape a window """

    def test_gdk_shape_is_applied(self) -> None:
        if not POSIX or OSX:
            raise unittest.SkipTest("the gdk shape can only be verified on X11")
        try:
            from xpra.x11.bindings.shape import XShapeBindings, SHAPE_KIND
        except ImportError as e:
            raise unittest.SkipTest(f"no X11 shape bindings: {e}")
        from xpra.x11.error import xsync
        from unit.process_test_util import DisplayContext
        kinds = {name: kind for kind, name in SHAPE_KIND.items()}
        with DisplayContext():
            Gtk = gi_import("Gtk")
            Gdk = gi_import("Gdk")
            initialized = Gtk.init_check()
            if isinstance(initialized, tuple):
                initialized = initialized[0]
            self.assertTrue(
                initialized, "Gtk failed to initialize on the test display")
            # `Gtk.Window()` checks the auto-init result cached when this module
            # was imported, before `DisplayContext` started its Xvfb.
            gtk_window = Gtk.Window.new(Gtk.WindowType.TOPLEVEL)
            gtk_window.set_default_size(*SIZE)
            mapped: list[bool] = []
            gtk_window.connect("map-event", lambda *_args: mapped.append(True))
            gtk_window.show()
            # gdk only applies the bounding shape to windows which are viewable,
            # so wait for the window to be mapped before shaping it:
            while not mapped:
                Gtk.main_iteration()
            gdk_window = gtk_window.get_window()
            xid = gdk_window.get_xid()
            try:
                with no_x11_bindings():
                    ShapeTestWindow(gdk_window).set_shape(SHAPE)
                # `invalidate_rect` queued an update, process it now
                # instead of waiting for the frame clock to tick:
                gdk_window.process_updates(True)
                Gdk.flush()
                with xsync:
                    XShape = XShapeBindings()
                    shapes = {name: XShape.XShapeGetRectangles(xid, kind) for name, kind in kinds.items()}
            finally:
                gtk_window.destroy()
                while Gtk.events_pending():
                    Gtk.main_iteration()
                # the window must be gone before the display is closed:
                del gdk_window, gtk_window
                gc.collect()
        self.assertEqual(shapes["Bounding"], [(10, 20, 150, 100)])
        self.assertEqual(shapes["ShapeInput"], [(10, 20, 50, 50)])
        # the `Clip` shape must have been left alone:
        self.assertEqual(shapes["Clip"], [(0, 0) + SIZE])


def main() -> None:
    unittest.main()


if __name__ == "__main__":
    main()
