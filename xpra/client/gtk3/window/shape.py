# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Sequence

from cairo import RectangleInt, Region  # pylint: disable=no-name-in-module

from xpra.client.gtk3.window.stub_window import GtkStubWindow
from xpra.util.env import envbool
from xpra.log import Logger

log = Logger("window", "shape")


bit_to_rectangles = None
try:
    from xpra.codecs.argb import argb

    bit_to_rectangles = argb.bit_to_rectangles
except (ImportError, AttributeError):
    pass
LAZY_SHAPE = envbool("XPRA_LAZY_SHAPE", not callable(bit_to_rectangles))


def add_border_rectangles(rectangles: Sequence[tuple[int, int, int, int]],
                          ww: int, wh: int, border_size: int) -> Sequence[tuple[int, int, int, int]]:
    from xpra.util.rectangle import add_rectangle, rectangle
    # convert to rectangle objects:
    rects = list(rectangle(*rect) for rect in rectangles)
    # add border rectangles:
    bsize = border_size
    for x, y, w, h in (
            (0, 0, ww, bsize),  # top
            (0, wh - bsize, ww, bsize),  # bottom
            (ww - bsize, bsize, bsize, wh-bsize*2),  # right
            (0, bsize, bsize, wh-bsize*2),  # left
    ):
        if w > 0 and h > 0:
            add_rectangle(rects, rectangle(x, y, w, h))
    # convert rectangles back to tuples:
    return tuple((rect.x, rect.y, rect.width, rect.height) for rect in rects)


class ShapeWindow(GtkStubWindow):

    def set_shape(self, shape) -> None:
        log("set_shape(%s)", shape)
        if not shape:
            return
        self.when_realized("shape", self.do_set_shape, shape)

    def get_shape_kinds(self) -> tuple[tuple[int, str], ...]:
        from xpra.client.gtk3.window.base import HAS_X11_BINDINGS
        if HAS_X11_BINDINGS:
            from xpra.x11.bindings.shape import SHAPE_KIND
            return tuple(SHAPE_KIND.items())
        # without the X11 bindings, we can only use the gdk api,
        # which has no equivalent for the `Clip` shape:
        # it would be applied as a bounding shape,
        # and since servers send it as a full window rectangle
        # for windows which only have a bounding shape,
        # that would undo the bounding shape we just applied.
        # (the kind values are unused with the gdk api)
        return (0, "Bounding"), (0, "ShapeInput")

    def do_set_shape(self, shape) -> None:
        from xpra.client.gtk3.window.base import HAS_X11_BINDINGS
        x_off, y_off = shape.get("x", 0), shape.get("y", 0)
        # adjust the offsets for scaling just once,
        # scaling them again for each shape kind would compound the scaling factor:
        scaling = self._xscale != 1 or self._yscale != 1
        if scaling:
            x_off, y_off = self.sx(x_off), self.sy(y_off)
        for kind, name in self.get_shape_kinds():
            rectangles = shape.get("%s.rectangles" % name)  # ie: Bounding.rectangles = [(0, 0, 150, 100)]
            if rectangles:
                if scaling:
                    rectangles = self.scale_shape_rectangles(name, rectangles)
                if name == "Bounding" and self.border.shown and self.border.size > 0:
                    ww, wh = self._size
                    rectangles = add_border_rectangles(rectangles, ww, wh, self.border.size)
                if HAS_X11_BINDINGS:
                    self.x11_shape_combine_rectangles(kind, name, x_off, y_off, rectangles)
                else:
                    self.gdk_shape_combine_rectangles(name, x_off, y_off, rectangles)

    def x11_shape_combine_rectangles(self, kind: int, name: str, x_off: int, y_off: int, rectangles) -> None:
        from xpra.x11.bindings.shape import XShapeBindings
        xid = self.get_window().get_xid()
        # too expensive to log with actual rectangles:
        log("XShapeCombineRectangles(%#x, %s, %i, %i, %i rects)", xid, name, x_off, y_off, len(rectangles))
        from xpra.x11.error import xlog
        with xlog:
            XShape = XShapeBindings()
            XShape.XShapeCombineRectangles(xid, kind, x_off, y_off, rectangles)

    def gdk_shape_combine_rectangles(self, name: str, x_off: int, y_off: int, rectangles) -> None:
        """
        Apply the shape using the gdk api, for clients without the X11 bindings.
        The gdk X11 backend maps both calls to `XShape`,
        the wayland backend can only honour the input shape
        (`shape_combine_region` is a no-op there),
        and the win32 backend uses `SetWindowRgn`.
        """
        gdk_window = self.get_window()
        region = Region()
        for rect in rectangles:
            region.union(RectangleInt(*rect))
        # too expensive to log with actual rectangles:
        log("gdk shape_combine_region(%s, %s, %i, %i, %i rects)", gdk_window, name, x_off, y_off, len(rectangles))
        if name == "ShapeInput":
            gdk_window.input_shape_combine_region(region, x_off, y_off)
            return
        gdk_window.shape_combine_region(region, x_off, y_off)
        # gdk only pushes the bounding shape to the window system
        # when it processes updates for a window with a dirty geometry,
        # and a shape which only shrinks the window invalidates nothing at all,
        # so make sure that there is something to process:
        gdk_window.invalidate_rect(None, True)

    def lazy_scale_shape(self, rectangles) -> list:
        # scale the rectangles without a bitmap...
        # results aren't so good! (but better than nothing?)
        return [self.srect(*x) for x in rectangles]

    def scale_shape_rectangles(self, kind_name, rectangles):
        if LAZY_SHAPE or len(rectangles) < 2:
            return self.lazy_scale_shape(rectangles)
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            return self.lazy_scale_shape(rectangles)
        ww, wh = self._size
        sw, sh = self.cp(ww, wh)
        img = Image.new('1', (sw, sh), color=0)
        log("drawing %s on bitmap(%s,%s)=%s", kind_name, sw, sh, img)
        d = ImageDraw.Draw(img)
        for x, y, w, h in rectangles:
            d.rectangle((x, y, x + w, y + h), fill=1)
        log("drawing complete")
        img = img.resize((ww, wh), resample=Image.BICUBIC)
        log("resized %s bitmap to window size %sx%s: %s", kind_name, ww, wh, img)
        # now convert back to rectangles...
        monodata = img.tobytes("raw", "1")
        log("got %i bytes", len(monodata))
        # log.warn("monodata: %s (%i bytes) %ix%i", repr_ellipsized(monodata), len(monodata), ww, wh)
        assert callable(bit_to_rectangles)
        # noinspection calling-non-callable
        rectangles = bit_to_rectangles(monodata, ww, wh)
        log("back to rectangles")
        return rectangles

    def set_bypass_compositor(self, v) -> None:
        if v not in (0, 1, 2):
            v = 0
        self.set_x11_property("_NET_WM_BYPASS_COMPOSITOR", "u32", v)
