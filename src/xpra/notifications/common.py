# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import BytesIOClass
from xpra.log import Logger
log = Logger("dbus", "notify")


def parse_image_data(data):
    try:
        width, height, rowstride, has_alpha, bpp, channels, image_data = data
        log("parse_image_data(%i, %i, %i, %s, %i, %i, %i bytes)", width, height, rowstride, bool(has_alpha), bpp, channels, len(image_data))
        from PIL import Image
        if channels==4:
            if has_alpha:
                rgb_format = "RGBA"
            else:
                rgb_format = "RGBX"
        elif channels==3:
            rgb_format = "RGB"
        img = Image.frombuffer("RGBA", (width, height), image_data, "raw", rgb_format, rowstride)
        return image_data(img)
    except Exception as e:
        log("parse_image_data(%s)", data, exc_info=True)
        log.error("Error parsing icon data for notification:")
        log.error(" %s", e)
    return None

def parse_image_path(path):
    try:
        from PIL import Image
        img = Image.open(path)
        return image_data(img)
    except Exception as e:
        log.error("Error parsing image path '%s' for notification:", path)
        log.error(" %s", e)
    return None

def image_data(img):
    buf = BytesIOClass()
    img.save(buf, "png")
    data = buf.getvalue()
    buf.close()
    w,h = img.size
    return ("png", w, h, data)
