# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Sequence

from xpra.net.compression import Compressed
from xpra.codecs.image import ImageWrapper
from xpra.log import Logger

log = Logger("encoding")


def make_screenshot_packet_from_regions(regions: Sequence[tuple[int, int, int, ImageWrapper]]) \
        -> tuple[str, int, int, str, int, Any]:
    # regions = array of (wid, x, y, PIL.Image)
    if not regions:
        log("screenshot: no regions found, returning empty 0x0 image!")
        return "screenshot", 0, 0, "png", 0, b""
    # in theory, we could run the rest in a non-UI thread since we're done with GTK..
    minx: int = min(x for (_, x, _, _) in regions)
    miny: int = min(y for (_, _, y, _) in regions)
    maxx: int = max((x + img.get_width()) for (_, x, _, img) in regions)
    maxy: int = max((y + img.get_height()) for (_, _, y, img) in regions)
    width = maxx - minx
    height = maxy - miny
    log("screenshot: %sx%s, min x=%s y=%s", width, height, minx, miny)
    from PIL import Image  # pylint: disable=import-outside-toplevel
    screenshot = Image.new("RGBA", (width, height))
    for wid, x, y, img in reversed(regions):
        pixel_format = img.get_pixel_format()
        target_format = {
            "XRGB": "RGB",
            "BGRX": "RGB",
            "BGRA": "RGBA",
        }.get(pixel_format, pixel_format)
        pixels = img.get_pixels()
        w = img.get_width()
        h = img.get_height()
        # PIL cannot use the memoryview directly:
        if isinstance(pixels, memoryview):
            pixels = pixels.tobytes()
        try:
            window_image = Image.frombuffer(target_format, (w, h), pixels, "raw", pixel_format, img.get_rowstride())
        except (ValueError, TypeError):
            log.error("Error parsing window pixels in %s format for window %i", pixel_format, wid, exc_info=True)
            continue
        tx = x - minx
        ty = y - miny
        screenshot.paste(window_image, (tx, ty))
    from io import BytesIO
    buf = BytesIO()
    screenshot.save(buf, "png")
    data = buf.getvalue()
    buf.close()
    compressed = Compressed("png", data)
    packet = ("screenshot", width, height, "png", width * 4, compressed)
    log("screenshot: %sx%s %s", width, height, compressed)
    return packet
