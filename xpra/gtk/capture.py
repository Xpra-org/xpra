# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic

from xpra.os_util import gi_import
from xpra.common import ScreenshotData
from xpra.codecs.image import ImageWrapper
from xpra.gtk.pixbuf import pixbuf_save_to_memory
from xpra.log import Logger

log = Logger("shadow")


def get_rgb_rawdata(window, x: int, y: int, width: int, height: int) \
        -> tuple[int, int, int, int, bytes, str, int, int, int] | None:
    """
        Extracts pixels from the given pixmap
    """
    start = monotonic()
    pixmap_w, pixmap_h = window.get_geometry()[2:4]
    # Just in case we somehow end up with damage larger than the pixmap,
    # we don't want to start requesting random chunks of memory (this
    # could happen if a window is resized, but we don't throw away our
    # existing damage map):
    if x < 0 or y < 0:
        raise ValueError(f"invalid position {x},{y}")
    if x + width > pixmap_w:
        width = pixmap_w - x
    if y + height > pixmap_h:
        height = pixmap_h - y
    if width <= 0 or height <= 0:
        return None
    Gdk = gi_import("Gdk")
    pixbuf = Gdk.pixbuf_get_from_window(window, x, y, width, height)
    log("get_rgb_rawdata(..) pixbuf.get_from_drawable took %s ms", int(1000 * (monotonic() - start)))
    raw_data = pixbuf.get_pixels()
    rowstride = pixbuf.get_rowstride()
    return x, y, width, height, raw_data, "RGB", 24, rowstride, 3


def take_png_screenshot(window) -> ScreenshotData | None:
    log("grabbing screenshot")
    w, h = window.get_geometry()[2:4]
    Gdk = gi_import("Gdk")
    pixbuf = Gdk.pixbuf_get_from_window(window, 0, 0, w, h)
    if not pixbuf:
        return None
    data = pixbuf_save_to_memory(pixbuf, "png")
    rowstride = w * 3
    return w, h, "png", rowstride, data


class GTKImageCapture:
    __slots__ = "window",

    def __init__(self, window):
        self.window = window

    def __repr__(self):
        return "GTKImageCapture(%s)" % self.window

    def get_type(self) -> str:
        return "GTK"

    def clean(self) -> None:
        """ subclasses may want to perform cleanup here """

    def refresh(self) -> bool:
        return True

    def get_image(self, x: int, y: int, width: int, height: int) -> ImageWrapper | None:
        attrs = get_rgb_rawdata(self.window, x, y, width, height)
        if not attrs:
            return None
        return ImageWrapper(*attrs)

    def take_screenshot(self) -> ScreenshotData | None:
        return take_png_screenshot(self.window)


def main(filename) -> int:
    from xpra.gtk.util import get_default_root_window
    root = get_default_root_window()
    data = take_png_screenshot(root)
    assert data
    with open(filename, "wb") as f:
        f.write(data[-1])
    return 0


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} filename.png")
        v = 1
    else:
        v = main(sys.argv[1])
    sys.exit(v)
