# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic
from xpra.codecs.loader import get_codec
from xpra.util import envbool, first_time
from xpra.log import Logger

log = Logger("window", "encoding")

WEBP_PILLOW = envbool("XPRA_WEBP_PILLOW", False)


def webp_encode(coding, image, options):
    stride = image.get_rowstride()
    pixel_format = image.get_pixel_format()
    enc_webp = get_codec("enc_webp")
    log("WEBP_PILLOW=%s, enc_webp=%s, stride=%s, pixel_format=%s", WEBP_PILLOW, enc_webp, stride, pixel_format)
    if not WEBP_PILLOW and enc_webp and pixel_format in ("BGRA", "BGRX", "RGBA", "RGBX", "RGB", "BGR"):
        #prefer Cython module:
        return enc_webp.encode(coding, image, options)
    #fallback using Pillow:
    enc_pillow = get_codec("enc_pillow")
    if enc_pillow:
        if not WEBP_PILLOW:
            log.warn("Warning: using PIL fallback for webp")
            log.warn(" enc_webp=%s, stride=%s, pixel format=%s", enc_webp, stride, image.get_pixel_format())
        for x in ("webp", "png", "jpeg"):
            if x in enc_pillow.get_encodings():
                return enc_pillow.encode(x, image, options)
    raise Exception("BUG: cannot use 'webp' encoding and none of the PIL fallbacks are available!")


def mmap_send(mmap, mmap_size, image, rgb_formats, supports_transparency):
    try:
        from xpra.net.mmap_pipe import mmap_write
    except ImportError:
        mmap_write = None               #no mmap
    if mmap_write is None:
        if first_time("mmap_write missing"):
            log.warn("Warning: cannot use mmap, no write method support")
        return None
    if image.get_pixel_format() not in rgb_formats:
        from xpra.codecs.rgb_transform import rgb_reformat  #pylint: disable=import-outside-toplevel
        if not rgb_reformat(image, rgb_formats, supports_transparency):
            warning_key = "mmap_send(%s)" % image.get_pixel_format()
            if first_time(warning_key):
                log.warn("Waening: cannot use mmap to send %s" % image.get_pixel_format())
            return None
    start = monotonic()
    data = image.get_pixels()
    assert data, "failed to get pixels from %s" % image
    mmap_data, mmap_free_size = mmap_write(mmap, mmap_size, data)
    elapsed = monotonic()-start+0.000000001 #make sure never zero!
    log("%s MBytes/s - %s bytes written to mmap in %.1f ms", int(len(data)/elapsed/1024/1024), len(data), 1000*elapsed)
    if mmap_data is None:
        return None
    #replace pixels with mmap info:
    return mmap_data, mmap_free_size, len(data)
