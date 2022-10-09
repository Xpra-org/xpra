# This file is part of Xpra.
# Copyright (C) 2018-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
from io import BytesIO

from xpra.util import first_time
from xpra.log import Logger

log = Logger("dbus", "notify")


def PIL_Image():
    try:
        # pylint: disable=import-outside-toplevel
        from PIL import Image
        return Image
    except ImportError:
        if first_time("parse-image-requires-pillow"):
            log.info("using notification icons requires python-pillow")
        return None


def parse_image_data(data):
    try:
        width, height, rowstride, has_alpha, bpp, channels, pixels = data
        log("parse_image_data(%i, %i, %i, %s, %i, %i, %i bytes)",
            width, height, rowstride, bool(has_alpha), bpp, channels, len(pixels))
        Image = PIL_Image()
        if not Image:
            return None
        if channels==4:
            rgb_format = "BGRA"
            fmt = "RGBA"
        elif channels==3:
            rgb_format = "BGR"
            fmt = "RGB"
        if isinstance(pixels, (list, tuple)):
            pixels = bytes(pixels)
        img = Image.frombytes(fmt, (width, height), pixels, "raw", rgb_format, rowstride)
        if channels==4 and not has_alpha:
            img = img.convert("RGB")
        return image_data(img)
    except Exception as e:
        log.error("Error parsing icon data for notification:", exc_info=True)
        log.estr(e)
    return None

def parse_image_path(path):
    if path and os.path.exists(path):
        Image = PIL_Image()
        if not Image:
            return None
        try:
            img = Image.open(path)
            return image_data(img)
        except Exception as e:
            log(f"failed to open image {path!r}", exc_info=True)
            log.error("Error loading image for notification")
            log.error(f" using path {path!r}:")
            estr = str(e)
            if estr.endswith(f"{path!r}"):
                estr=estr[:-len(f"{path!r}")]
            log.error(f" {estr}")
    return None

def image_data(img):
    buf = BytesIO()
    img.save(buf, "png")
    data = buf.getvalue()
    buf.close()
    w,h = img.size
    return ("png", w, h, data)
