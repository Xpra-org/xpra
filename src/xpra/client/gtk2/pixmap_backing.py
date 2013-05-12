# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk
from gtk import gdk
import cairo

from xpra.log import Logger
log = Logger()

from xpra.client.gtk2.window_backing import GTK2WindowBacking

"""
Backing using a gdk.Pixmap
"""
class PixmapBacking(GTK2WindowBacking):

    def __init__(self, wid, w, h, has_alpha):
        GTK2WindowBacking.__init__(self, wid, w, h, has_alpha)

    def init(self, w, h, has_alpha):
        old_backing = self._backing
        assert w<32768 and h<32768, "dimensions too big: %sx%s" % (w, h)
        self._has_alpha = has_alpha
        if has_alpha:
            self._backing = gdk.Pixmap(None, w, h, 32)
            screen = self._backing.get_screen()
            rgba = screen.get_rgba_colormap()
            if rgba is not None:
                self._backing.set_colormap(rgba)
            else:
                self._has_alpha = False
        if not self._has_alpha:
            self._backing = gdk.Pixmap(gdk.get_default_root_window(), w, h)
        cr = self._backing.cairo_create()
        cr.set_source_rgb(1, 1, 1)
        if old_backing is not None:
            # Really we should respect bit-gravity here but... meh.
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_pixmap(old_backing, 0, 0)
            cr.paint()
            old_w, old_h = old_backing.get_size()
            if w>old_w:
                cr.move_to(old_w, 0)
                cr.line_to(w, 0)
                cr.line_to(w, h)
                cr.line_to(0, h)
                cr.fill()
            if h>old_h:
                cr.move_to(0, old_h)
                cr.line_to(0, h)
                cr.line_to(w, h)
                cr.line_to(w, old_h)
                cr.fill()
            #note: we may paint the rectangle (old_w, old_h) to (w, h) twice - no big deal
        else:
            cr.rectangle(0, 0, w, h)
            cr.fill()

    def _do_paint_rgb24(self, img_data, x, y, width, height, rowstride, options, callbacks):
        gc = self._backing.new_gc()
        self._backing.draw_rgb_image(gc, x, y, width, height, gdk.RGB_DITHER_NONE, img_data, rowstride)
        return True

    def _do_paint_rgb32(self, img_data, x, y, width, height, rowstride, options, callbacks):
        log.debug("do_paint_rgb32(%s bytes, %s, %s, %s, %s, %s, %s, %s)", len(img_data), x, y, width, height, rowstride, options, callbacks)
        #log.info("data head=%s", [hex(ord(v))[2:] for v in list(img_data[:500])])
        pixbuf = gdk.pixbuf_new_from_data(img_data, gtk.gdk.COLORSPACE_RGB, True, 8, width, height, rowstride)
        log.debug("do_paint_rgb32(..) backing depth=%s", self._backing.get_depth())
        cr = self._backing.cairo_create()
        cr.rectangle(x, y, width, height)
        cr.set_source_pixbuf(pixbuf, x, y)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.paint()
        return True
