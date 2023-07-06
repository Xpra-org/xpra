# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic
from typing import Dict, Tuple

from xpra.os_util import memoryview_to_bytes
from xpra.util import first_time, csv
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.log import Logger
try:
    from xpra.codecs.argb.argb import argb_swap #@UnresolvedImport
except ImportError:     # pragma: no cover
    argb_swap = None

#"pixels_to_bytes" gets patched up by the OSX shadow server
pixels_to_bytes = memoryview_to_bytes

log = Logger("encoding")


#source format  : [(PIL input format, output format), ..]
PIL_conv : Dict[str, Tuple[Tuple[str,str], ...]] = {
             "XRGB"   : (("XRGB", "RGB"), ),
             #try to drop alpha channel since it isn't used:
             "BGRX"   : (("BGRX", "RGB"), ("BGRX", "RGBX")),
             #try with alpha first:
             "BGRA"   : (("BGRA", "RGBA"), ("BGRX", "RGB"), ("BGRX", "RGBX")),
             }
#as above but for clients which cannot handle alpha:
PIL_conv_noalpha : Dict[str, Tuple[Tuple[str,str], ...]] = {
             "XRGB"   : (("XRGB", "RGB"), ),
             #try to drop alpha channel since it isn't used:
             "BGRX"   : (("BGRX", "RGB"), ("BGRX", "RGBX")),
             #try with alpha first:
             "BGRA"   : (("BGRX", "RGB"), ("BGRA", "RGBA"), ("BGRX", "RGBX")),
             }


def rgb_reformat(image : ImageWrapper, rgb_formats, supports_transparency:bool) -> bool:
    """ convert the RGB pixel data into a format supported by the client """
    #need to convert to a supported format!
    pixel_format = image.get_pixel_format()
    pixels = image.get_pixels()
    if not pixels:
        raise RuntimeError(f"failed to get pixels from {image}")
    if pixel_format in ("r210", "BGR565"):
        #try to fall back to argb module
        #(required for r210 which is not handled by PIL directly)
        assert argb_swap, "no argb codec"
        log("rgb_reformat: using argb_swap for %s", image)
        return argb_swap(image, rgb_formats, supports_transparency)
    modes : Tuple[Tuple[str,str], ...] = ()
    try:
        # pylint: disable=import-outside-toplevel
        from PIL import Image
    except ImportError:
        log("PIL.Image not found!")
        Image = None
    else:
        if supports_transparency:
            modes = PIL_conv.get(pixel_format, ())
        else:
            modes = PIL_conv_noalpha.get(pixel_format, ())
    target_rgb : Tuple[Tuple[str,str], ...] = tuple((im,om) for (im,om) in modes if om in rgb_formats)
    if not target_rgb:
        log("rgb_reformat: no matching target modes for converting %s to %s", image, rgb_formats)
        #try argb module:
        assert argb_swap, "no argb codec"
        if argb_swap(image, rgb_formats, supports_transparency):
            return True
        warning_key = f"rgb_reformat({pixel_format}, {rgb_formats}, {supports_transparency})"
        if first_time(warning_key):
            log.warn(f"Warning: cannot convert {pixel_format!r} to one of: "+csv(rgb_formats))
        return False
    assert Image is not None
    input_format, target_format = target_rgb[0]
    start = monotonic()
    w = image.get_width()
    h = image.get_height()
    #PIL cannot use the memoryview directly:
    if isinstance(pixels, memoryview):
        pixels = pixels.tobytes()
    img = Image.frombuffer(target_format, (w, h), pixels, "raw", input_format, image.get_rowstride())
    rowstride = w*len(target_format)    #number of characters is number of bytes per pixel!
    data = img.tobytes("raw", target_format)
    if len(data)!=rowstride*h:
        raise RuntimeError(f"expected {rowstride*h} bytes in {target_format} format but got {len(data)}")
    image.set_pixels(data)
    image.set_rowstride(rowstride)
    image.set_pixel_format(target_format)
    end = monotonic()
    log("rgb_reformat(%s, %s, %s) converted from %s (%s bytes) to %s (%s bytes) in %.1fms, rowstride=%s",
        image, rgb_formats, supports_transparency, pixel_format, len(pixels),
        target_format, len(data), (end-start)*1000.0, rowstride)
    return True
