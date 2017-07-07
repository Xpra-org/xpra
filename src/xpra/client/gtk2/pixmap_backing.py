# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from gtk import gdk
import cairo

from xpra.log import Logger
log = Logger("paint")

from xpra.client.gtk2.window_backing import GTK2WindowBacking
from xpra.client.window_backing_base import fire_paint_callbacks
from xpra.os_util import memoryview_to_bytes, monotonic_time
from xpra.util import csv, envbool


PIXMAP_RGB_MODES = ["RGB", "RGBX", "RGBA"]
INDIRECT_BGR = envbool("XPRA_PIXMAP_INDIRECT_BGR", False)
if INDIRECT_BGR:
    PIXMAP_RGB_MODES += ["BGRX", "BGRA", "BGR"]


INTERP_DICT = {
    "nearest"    : gdk.INTERP_NEAREST,
    "tiles"      : gdk.INTERP_TILES,
    "bilinear"   : gdk.INTERP_BILINEAR,
    "hyper"      : gdk.INTERP_HYPER,
    }
SCALING_INTERP_STR = os.environ.get("XPRA_SCALING_INTERPOLATION", "HYPER").lower()
SCALING_INTERP = INTERP_DICT.get(SCALING_INTERP_STR)
if not SCALING_INTERP:
    log.warn("Warning: invalid interpolation '%s'")
    log.warn(" supported types: %s", csv(INTERP_DICT.keys()))

"""
Backing using a gdk.Pixmap
"""
class PixmapBacking(GTK2WindowBacking):

    HAS_ALPHA = False
    RGB_MODES = PIXMAP_RGB_MODES

    def __repr__(self):
        return "PixmapBacking(%s)" % self._backing

    def init(self, ww, wh, bw, bh):
        #use window size as backing size:
        self.render_size = ww, wh
        self.size = bw, bh
        old_backing = self._backing
        self.do_init_new_backing_instance()
        self.copy_backing(old_backing)

    def do_init_new_backing_instance(self):
        w, h = self.size
        self._backing = None
        assert w<32768 and h<32768, "dimensions too big: %sx%s" % (w, h)
        if w==0 or h==0:
            #this can happen during cleanup
            return
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

    def copy_backing(self, old_backing):
        w, h = self.size
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

    def paint_jpeg(self, img_data, x, y, width, height, options, callbacks):
        img = self.jpeg_decoder.decompress_to_rgb("RGBX", img_data, width, height, options)
        rgb_format = img.get_pixel_format()
        img_data = img.get_pixels()
        rowstride = img.get_rowstride()
        w = img.get_width()
        h = img.get_height()
        self.idle_add(self.paint_rgb, rgb_format, img_data, x, y, w, h, rowstride, options, callbacks)

    def paint_scroll(self, x, y, width, height, img_data, options, callbacks):
        #Warning: unused as this causes strange visual corruption
        self.idle_add(self.do_paint_scroll, x, y, width, height, img_data, options, callbacks)

    def do_paint_scroll(self, x, y, w, h, scrolls, options, callbacks):
        gc = self._backing.new_gc()
        for sx,sy,sw,sh,xdelta,ydelta in scrolls:
            self._backing.draw_drawable(gc, self._backing, sx, sy, sx+xdelta, sy+ydelta, sw, sh)
        fire_paint_callbacks(callbacks)

    def bgr_to_rgb(self, img_data, width, height, rowstride, rgb_format, target_format):
        if not rgb_format.startswith("BGR"):
            return img_data, rowstride
        from xpra.codecs.loader import get_codec
        #use an rgb format name that PIL will recognize:
        in_format = rgb_format.replace("X", "A")
        PIL = get_codec("PIL")
        img = PIL.Image.frombuffer(target_format, (width, height), img_data, "raw", in_format, rowstride)
        img_data = img.tobytes("raw", target_format)
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
            #no alpha or scaling is easier:
            gc = self._backing.new_gc()
            self._backing.draw_rgb_32_image(gc, x, y, width, height, gdk.RGB_DITHER_NONE, img_data, rowstride)
        return True

    def cairo_draw(self, context):
        self.cairo_draw_from_drawable(context, self._backing)


    def cairo_draw_from_drawable(self, context, drawable):
        if drawable is None:
            return
        try:
            ww, wh = self.render_size
            w, h = self.size
            if ww==0 or w==0 or wh==0 or h==0:
                return False
            if w!=ww or h!=wh:
                context.scale(float(ww)/w, float(wh)/h)
            x, y = self.offsets[:2]
            if x!=0 or y!=0:
                context.translate(x, y)
            context.set_source_pixmap(drawable, 0, 0)
            context.set_operator(cairo.OPERATOR_SOURCE)
            context.paint()
            if self.pointer_overlay:
                x, y, size, start_time = self.pointer_overlay[2:]
                elapsed = max(0, monotonic_time()-start_time)
                if elapsed<6:
                    alpha = max(0, (5.0-elapsed)/5.0)
                    log("cairo_draw_from_drawable(%s, %s) drawing pointer with cairo at %s with alpha=%s", context, drawable, self.pointer_overlay, alpha)
                    context.set_source_rgba(0, 0, 0, alpha)
                    context.set_line_width(1)
                    context.move_to(x-size, y)
                    context.line_to(x+size, y)
                    context.stroke()
                    context.move_to(x, y-size)
                    context.line_to(x, y+size)
                    context.stroke()
                else:
                    self.pointer_overlay = None
            return True
        except KeyboardInterrupt:
            raise
        except:
            log.error("cairo_draw_from_drawable(%s, %s)", context, drawable, exc_info=True)
            return False
