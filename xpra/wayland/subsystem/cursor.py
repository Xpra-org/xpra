# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.codecs.image import ImageWrapper
from xpra.server.source.cursor import CursorsConnection
from xpra.server.subsystem.cursor import CursorManager
from xpra.log import Logger

log = Logger("server", "wayland", "cursor")


CURSOR_SIZE = 24
CURSOR_SERIAL = 1


def make_default_cursor(size: int = CURSOR_SIZE) -> bytes:
    pixels = bytearray(size * size * 4)
    points = (
        (0, 0), (0, 17), (5, 13), (8, 22), (12, 20), (9, 12), (15, 12),
    )

    def inside(x: int, y: int) -> bool:
        inside_polygon = False
        px, py = points[-1]
        for qx, qy in points:
            if ((qy > y) != (py > y)) and x < (px - qx) * (y - qy) / (py - qy) + qx:
                inside_polygon = not inside_polygon
            px, py = qx, qy
        return inside_polygon

    for y in range(size):
        for x in range(size):
            if not inside(x, y):
                continue
            border = not inside(x - 1, y) or not inside(x + 1, y) or not inside(x, y - 1) or not inside(x, y + 1)
            offset = (y * size + x) * 4
            if border:
                pixels[offset:offset + 4] = b"\x00\x00\x00\xff"
            else:
                pixels[offset:offset + 4] = b"\xff\xff\xff\xff"
    return bytes(pixels)


class WaylandCursorManager(CursorManager):

    def __init__(self, server=None):
        super().__init__(server)
        pixels = make_default_cursor()
        self.default_image = (0, 0, CURSOR_SIZE, CURSOR_SIZE, 0, 0, CURSOR_SERIAL, pixels, "left_ptr")
        self.current_image = self.default_image
        self.last_image = self.default_image
        self.serial = CURSOR_SERIAL
        self.cursor_tracker = None

    def connect_compositor(self, compositor) -> None:
        from xpra.wayland.cursor import SeatCursorTracker
        self.cursor_tracker = SeatCursorTracker(compositor.get_seat_ptr(), self.cursor)

    def cleanup(self) -> None:
        if self.cursor_tracker:
            self.cursor_tracker.cleanup()
            self.cursor_tracker = None

    def get_default_cursor_size(self) -> tuple[int, int]:
        return CURSOR_SIZE, CURSOR_SIZE

    def get_max_cursor_size(self) -> tuple[int, int]:
        return 32767, 32767

    def get_cursor_data(self, skip_default=True) -> tuple[Any, Any]:
        if not self.enabled:
            return None, []
        cursor_image = self.current_image
        if not cursor_image:
            return None, []
        self.last_image = cursor_image
        cursor_info = cursor_image[:7] + ("%i bytes" % len(cursor_image[7]), cursor_image[8])
        log("get_cursor_data(%s)=%s", skip_default, cursor_info)
        return cursor_image, (self.get_default_cursor_size(), self.get_max_cursor_size())

    def cursor(self, image: ImageWrapper | None, hotspot_x: int, hotspot_y: int) -> None:
        if image is None:
            self.current_image = None
            self.last_image = ()
            self.notify_cursor_changed()
            return
        self.serial += 1
        self.current_image = self.make_cursor_image(image, hotspot_x, hotspot_y, self.serial)
        self.last_image = self.current_image
        self.notify_cursor_changed()

    def notify_cursor_changed(self) -> None:
        for ss in self.get_sources_by_type(CursorsConnection):
            ss.send_cursor()

    @staticmethod
    def make_cursor_image(image: ImageWrapper, hotspot_x: int, hotspot_y: int, serial: int) -> tuple:
        width = image.get_width()
        height = image.get_height()
        pixel_format = image.get_pixel_format()
        rowstride = image.get_rowstride()
        if isinstance(rowstride, (tuple, list)):
            rowstride = rowstride[0]
        rowstride = int(rowstride)
        pixels = bytes(image.get_pixels())
        if pixel_format == "RGBA" and rowstride == width * 4:
            rgba = pixels
        else:
            rgba_buffer = bytearray(width * height * 4)
            for y in range(height):
                src = y * rowstride
                dst = y * width * 4
                for x in range(width):
                    si = src + x * 4
                    di = dst + x * 4
                    if pixel_format == "BGRA":
                        rgba_buffer[di] = pixels[si + 2]
                        rgba_buffer[di + 1] = pixels[si + 1]
                        rgba_buffer[di + 2] = pixels[si]
                        rgba_buffer[di + 3] = pixels[si + 3]
                    else:
                        rgba_buffer[di:di + 4] = pixels[si:si + 4]
            rgba = bytes(rgba_buffer)
        hotspot_x = max(0, min(hotspot_x, width - 1))
        hotspot_y = max(0, min(hotspot_y, height - 1))
        return 0, 0, width, height, hotspot_x, hotspot_y, serial, rgba, "wayland"
