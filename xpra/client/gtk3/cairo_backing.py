# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Sequence

from cairo import Format

from xpra.os_util import gi_import
from xpra.util.env import envbool
from xpra.util.objects import typedict
from xpra.client.gtk3.cairo_backing_base import CairoBackingBase, FORMATS
from xpra.gtk.cairo_image import make_image_surface, CAIRO_FORMATS
from xpra.log import Logger

log = Logger("paint", "cairo")

GLib = gi_import("GLib")
GdkPixbuf = gi_import("GdkPixbuf")

CAIRO_USE_PIXBUF = envbool("XPRA_CAIRO_USE_PIXBUF", False)


class CairoBacking(CairoBackingBase):
    """
    An area we draw onto with cairo
    This requires `cairo_bindings`.
    """

    RGB_MODES: Sequence[str] = ("BGRA", "BGRX", "RGBA", "RGBX", "BGR", "RGB", "r210", "BGR565")

    def __repr__(self):
        b = self._backing
        if b:
            binfo = "ImageSurface(%i, %i)" % (b.get_width(), b.get_height())
        else:
            binfo = "None"
        return "bindings.CairoBacking(%s : size=%s, render_size=%s)" % (binfo, self.size, self.render_size)

    def _do_paint_rgb(self, cairo_format, has_alpha: bool, img_data,
                      x: int, y: int, width: int, height: int, render_width: int, render_height: int,
                      rowstride: int, options: typedict) -> None:
        """ must be called from UI thread """
        log("cairo._do_paint_rgb%s make_image_surface=%s, use pixbuf=%s",
            (FORMATS.get(cairo_format, cairo_format), has_alpha, len(img_data),
             type(img_data), x, y, width, height, render_width, render_height,
             rowstride, options), make_image_surface, CAIRO_USE_PIXBUF)
        rgb_format = options.strget("rgb_format", "RGB")
        if not CAIRO_USE_PIXBUF:
            rgb_formats = CAIRO_FORMATS.get(cairo_format, ())
            if rgb_format in rgb_formats:
                img_surface = make_image_surface(cairo_format, rgb_format, img_data, width, height, rowstride)
                self.cairo_paint_surface(img_surface, x, y, render_width, render_height, options)
                img_surface.finish()
                return
            log("cannot set image surface data for cairo format %s and rgb_format %s (rgb formats supported: %s)",
                FORMATS.get(cairo_format, cairo_format), rgb_format, rgb_formats)

        if rgb_format in ("RGB", "RGBA", "RGBX"):
            data = GLib.Bytes(img_data)
            pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(data, GdkPixbuf.Colorspace.RGB,
                                                     has_alpha, 8, width, height, rowstride)
            if render_width != width or render_height != height:
                resample = options.strget("resample", "bilinear")
                if resample == "NEAREST":
                    interp_type = GdkPixbuf.InterpType.NEAREST
                elif resample in ("BICUBIC", "LANCZOS"):
                    interp_type = GdkPixbuf.InterpType.HYPER
                else:
                    interp_type = GdkPixbuf.InterpType.BILINEAR
                log(f"scaling using {resample!r} from {width}x{height} to {render_width}x{render_height}")
                pixbuf = pixbuf.scale_simple(render_width, render_height, interp_type)
            self.cairo_paint_pixbuf(pixbuf, x, y, options)
            return

        raise ValueError(f"failed to paint {cairo_format}")

    def update_fps_buffer(self, width: int, height: int, pixels) -> None:
        self.fps_image = make_image_surface(Format.ARGB32, "RGBA", pixels, width, height, width * 4)
