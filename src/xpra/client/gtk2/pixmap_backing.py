# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from gtk import gdk
import cairo

from xpra.log import Logger
log = Logger("paint")

from xpra.client.gtk2.window_backing import GTK2WindowBacking
from xpra.os_util import memoryview_to_bytes


PIXMAP_RGB_MODES = ["RGB", "RGBX", "RGBA"]
INDIRECT_BGR = os.environ.get("XPRA_PIXMAP_INDIRECT_BGR", "0")=="1"
if INDIRECT_BGR:
    PIXMAP_RGB_MODES += ["BGRX", "BGRA", "BGR"]


"""
Backing using a gdk.Pixmap
"""
class PixmapBacking(GTK2WindowBacking):

    RGB_MODES = PIXMAP_RGB_MODES

    def __repr__(self):
        return "PixmapBacking(%s)" % self._backing

    def __init__(self, wid, w, h, has_alpha):
        self._backing = None
        GTK2WindowBacking.__init__(self, wid, has_alpha)

    def init(self, w, h):
        old_backing = self._backing
        assert w<32768 and h<32768, "dimensions too big: %sx%s" % (w, h)
        if self._alpha_enabled:
            self._backing = gdk.Pixmap(None, w, h, 32)
            screen = self._backing.get_screen()
            rgba = screen.get_rgba_colormap()
            if rgba is not None:
                self._backing.set_colormap(rgba)
            else:
                #cannot use transparency
                log.warn("cannot use transparency: no RGBA colormap!")
                self._alpha_enabled = False
                self._backing = gdk.Pixmap(gdk.get_default_root_window(), w, h)
        else:
            self._backing = gdk.Pixmap(gdk.get_default_root_window(), w, h)
        cr = self._backing.cairo_create()
        cr.set_source_rgb(1, 1, 1)
        if old_backing is not None:
            # Really we should respect bit-gravity here but... meh.
            old_w, old_h = old_backing.get_size()
            if w>old_w and h>old_h:
                #both width and height are bigger:
                cr.rectangle(old_w, 0, w-old_w, h)
                cr.fill()
                cr.new_path()
                cr.rectangle(0, old_h, old_w, h-old_h)
                cr.fill()
            elif w>old_w:
                #enlarged in width only
                cr.rectangle(old_w, 0, w-old_w, h)
                cr.fill()
            if h>old_h:
                #enlarged in height only
                cr.rectangle(0, old_h, w, h-old_h)
                cr.fill()
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_pixmap(old_backing, 0, 0)
            cr.paint()
        else:
            cr.rectangle(0, 0, w, h)
            cr.fill()

    def bgr_to_rgb(self, img_data, width, height, rowstride, rgb_format, target_format):
        if not rgb_format.startswith("BGR"):
            return img_data, rowstride
        from xpra.codecs.loader import get_codec
        #use an rgb format name that PIL will recognize:
        in_format = rgb_format.replace("X", "A")
        PIL = get_codec("PIL")
        img = PIL.Image.frombuffer(target_format, (width, height), img_data, "raw", in_format, rowstride)
        data_fn = getattr(img, "tobytes", getattr(img, "tostring"))
        img_data = data_fn("raw", target_format)
        log.warn("%s converted to %s", rgb_format, target_format)
        return img_data, width*len(target_format)

    def _do_paint_rgb24(self, img_data, x, y, width, height, rowstride, options):
        img_data = memoryview_to_bytes(img_data)
        if INDIRECT_BGR:
            img_data, rowstride = self.bgr_to_rgb(img_data, width, height, rowstride, options.strget("rgb_format", ""), "RGB")
        gc = self._backing.new_gc()
        self._backing.draw_rgb_image(gc, x, y, width, height, gdk.RGB_DITHER_NONE, img_data, rowstride)
        return True

    def _do_paint_rgb32(self, img_data, x, y, width, height, rowstride, options):
        has_alpha = options.boolget("has_alpha", False) or options.get("rgb_format", "").find("A")>=0
        if has_alpha:
            img_data = self.unpremultiply(img_data)
        img_data = memoryview_to_bytes(img_data)
        if INDIRECT_BGR:
            img_data, rowstride = self.bgr_to_rgb(img_data, width, height, rowstride, options.strget("rgb_format", ""), "RGBA")
        if has_alpha:
            #draw_rgb_32_image does not honour alpha, we have to use pixbuf:
            pixbuf = gdk.pixbuf_new_from_data(img_data, gdk.COLORSPACE_RGB, True, 8, width, height, rowstride)
            cr = self._backing.cairo_create()
            cr.rectangle(x, y, width, height)
            cr.set_source_pixbuf(pixbuf, x, y)
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.paint()
        else:
            #no alpha is easier:
            gc = self._backing.new_gc()
            self._backing.draw_rgb_32_image(gc, x, y, width, height, gdk.RGB_DITHER_NONE, img_data, rowstride)
        return True
