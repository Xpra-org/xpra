# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("encoding")

from PIL import Image
from xpra.codecs.loader import get_codec
from xpra.os_util import bytestostr, monotonic_time
try:
    from xpra.codecs.argb.argb import argb_swap, warn_encoding_once #@UnresolvedImport
except ImportError:
    argb_swap = warn_encoding_once = None


#source format  : [(PIL input format, output format), ..]
PIL_conv = {
             "XRGB"   : [("XRGB", "RGB")],
             #try to drop alpha channel since it isn't used:
             "BGRX"   : [("BGRX", "RGB"), ("BGRX", "RGBX")],
             #try with alpha first:
             "BGRA"   : [("BGRA", "RGBA"), ("BGRX", "RGB"), ("BGRX", "RGBX")],
             }
#as above but for clients which cannot handle alpha:
PIL_conv_noalpha = {
             "XRGB"   : [("XRGB", "RGB")],
             #try to drop alpha channel since it isn't used:
             "BGRX"   : [("BGRX", "RGB"), ("BGRX", "RGBX")],
             #try with alpha first:
             "BGRA"   : [("BGRX", "RGB"), ("BGRA", "RGBA"), ("BGRX", "RGBX")],
             }


def rgb_reformat(image, rgb_formats, supports_transparency):
    """ convert the RGB pixel data into a format supported by the client """
    #need to convert to a supported format!
    PIL = get_codec("PIL")
    pixel_format = bytestostr(image.get_pixel_format())
    pixels = image.get_pixels()
    assert pixels, "failed to get pixels from %s" % image
    if not PIL or pixel_format in ("r210", "BGR565"):
        #try to fallback to argb module
        #(required for r210 which is not handled by PIL directly)
        assert argb_swap, "no argb codec"
        log("rgb_reformat: using argb_swap for %s", image)
        return argb_swap(image, rgb_formats, supports_transparency)
    if supports_transparency:
        modes = PIL_conv.get(pixel_format)
    else:
        modes = PIL_conv_noalpha.get(pixel_format)
    assert modes, "no PIL conversion from %s" % (pixel_format)
    target_rgb = [(im,om) for (im,om) in modes if om in rgb_formats]
    if len(target_rgb)==0:
        log("rgb_reformat: no matching target modes for converting %s to %s", image, rgb_formats)
        #try argb module:
        assert argb_swap, "no argb codec"
        if argb_swap(image, rgb_formats, supports_transparency):
            return True
        warning_key = "rgb_reformat(%s, %s, %s)" % (pixel_format, rgb_formats, supports_transparency)
        warn_encoding_once(warning_key, "cannot convert %s to one of: %s" % (pixel_format, rgb_formats))
        return False
    input_format, target_format = target_rgb[0]
    start = monotonic_time()
    w = image.get_width()
    h = image.get_height()
    #PIL cannot use the memoryview directly:
    if isinstance(pixels, memoryview):
        pixels = pixels.tobytes()
    #log("rgb_reformat: converting %s from %s to %s using PIL, %i bytes", image, input_format, target_format, len(pixels))
    img = Image.frombuffer(target_format, (w, h), pixels, "raw", input_format, image.get_rowstride())
    rowstride = w*len(target_format)    #number of characters is number of bytes per pixel!
    data = img.tobytes("raw", target_format)
    assert len(data)==rowstride*h, "expected %s bytes in %s format but got %s" % (rowstride*h, len(data))
    image.set_pixels(data)
    image.set_rowstride(rowstride)
    image.set_pixel_format(target_format)
    end = monotonic_time()
    log("rgb_reformat(%s, %s, %s) converted from %s (%s bytes) to %s (%s bytes) in %.1fms, rowstride=%s", image, rgb_formats, supports_transparency, pixel_format, len(pixels), target_format, len(data), (end-start)*1000.0, rowstride)
    return True
