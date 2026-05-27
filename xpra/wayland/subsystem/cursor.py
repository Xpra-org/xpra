# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

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
        self.last_image = self.default_image

    def get_default_cursor_size(self) -> tuple[int, int]:
        return CURSOR_SIZE, CURSOR_SIZE

    def get_max_cursor_size(self) -> tuple[int, int]:
        return 32767, 32767

    def get_cursor_data(self, skip_default=True) -> tuple[Any, Any]:
        if not self.enabled:
            return None, []
        self.last_image = self.default_image
        cursor_info = self.default_image[:7] + ("%i bytes" % len(self.default_image[7]), self.default_image[8])
        log("get_cursor_data(%s)=%s", skip_default, cursor_info)
        return self.default_image, ((CURSOR_SIZE, CURSOR_SIZE), self.get_max_cursor_size())
