# This file is part of Xpra.
# Copyright (C) 2018-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
from io import BytesIO

from xpra.log import Logger

log = Logger("dbus", "notify")


def parse_image_data(data):
    try:
        width, height, rowstride, has_alpha, bpp, channels, pixels = data
        log("parse_image_data(%i, %i, %i, %s, %i, %i, %i bytes)",
            width, height, rowstride, bool(has_alpha), bpp, channels, len(pixels))
        from PIL import Image
        if channels==4:
            rgb_format = "BGRA"
            fmt = "RGBA"
        elif channels==3:
            rgb_format = "BGR"
            fmt = "RGB"
        img = Image.frombytes(fmt, (width, height), pixels, "raw", rgb_format, rowstride)
        if channels==4 and not has_alpha:
            img = img.convert("RGB")
        return image_data(img)
    except Exception as e:
        log("parse_image_data(%s)", data, exc_info=True)
        log.error("Error parsing icon data for notification:")
        log.error(" %s", e)
    return None

def parse_image_path(path):
    if path and os.path.exists(path):
        try:
            from PIL import Image
            img = Image.open(path)
            return image_data(img)
        except Exception as e:
            log("failed to open image '%s'", path, exc_info=True)
            log.error("Error loading image for notification")
            log.error(" using path '%s':", path)
            estr = str(e)
            if estr.endswith("%r" % path):
                estr=estr[:-len("%r"  % path)]
            log.error(" %s", estr)
    return None

def image_data(img):
    buf = BytesIO()
    img.save(buf, "png")
    data = buf.getvalue()
    buf.close()
    w,h = img.size
    return ("png", w, h, data)
