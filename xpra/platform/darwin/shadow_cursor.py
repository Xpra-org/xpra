# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from zlib import crc32

import Quartz.CoreGraphics as CG
from AppKit import NSCursor

from xpra.server.shadow.cursor import ShadowCursorManager
from xpra.log import Logger

cursorlog = Logger("cursor")


def get_cursor_cgimage(nsimage):
    # pick the bitmap representation that matches the image's logical (point)
    # size, so the cursor lines up with the logical screen capture;
    # fall back to the first available representation:
    size = nsimage.size()
    point_width = round(size.width)
    chosen = None
    for rep in nsimage.representations():
        if not hasattr(rep, "CGImage"):
            continue
        if chosen is None:
            chosen = rep
        if rep.pixelsWide() == point_width:
            chosen = rep
            break
    if chosen is None:
        return None
    return chosen.CGImage()


def get_cursor_pixels(cgimage) -> tuple[int, int, bytes]:
    # render the cursor image into a known BGRA bitmap context
    # (premultiplied alpha, rowstride = width * 4) so the pixels match
    # the format expected by the cursor packet encoder:
    width = CG.CGImageGetWidth(cgimage)
    height = CG.CGImageGetHeight(cgimage)
    if not width or not height:
        return 0, 0, b""
    rowstride = width * 4
    colorspace = CG.CGColorSpaceCreateDeviceRGB()
    bitmap_info = CG.kCGImageAlphaPremultipliedFirst | CG.kCGBitmapByteOrder32Little
    context = CG.CGBitmapContextCreate(None, width, height, 8, rowstride, colorspace, bitmap_info)
    if context is None:
        cursorlog("failed to create a %ix%i bitmap context for the cursor", width, height)
        return 0, 0, b""
    CG.CGContextDrawImage(context, CG.CGRectMake(0, 0, width, height), cgimage)
    image = CG.CGBitmapContextCreateImage(context)
    provider = CG.CGImageGetDataProvider(image)
    data = CG.CGDataProviderCopyData(provider)
    return width, height, bytes(data)


class DarwinShadowCursorManager(ShadowCursorManager):
    """
    macOS cursor subsystem for shadow servers.

    Captures the current system cursor pixels so that clients can render it,
    since the screen capture backends are configured not to composite the
    cursor into the framebuffer.
    """

    def do_get_cursor_data(self) -> tuple | None:
        cursor = NSCursor.currentSystemCursor()
        if cursor is None:
            cursorlog("do_get_cursor_data() no current system cursor")
            return self.last_cursor_data
        nsimage = cursor.image()
        if nsimage is None:
            cursorlog("do_get_cursor_data() cursor has no image")
            return self.last_cursor_data
        cgimage = get_cursor_cgimage(nsimage)
        if cgimage is None:
            cursorlog("do_get_cursor_data() cannot get a CGImage from %s", nsimage)
            return self.last_cursor_data
        width, height, pixels = get_cursor_pixels(cgimage)
        if not pixels:
            return self.last_cursor_data
        # the hotspot is expressed in the image's point coordinate system
        # (origin at the top-left), scale it to the pixel dimensions:
        size = nsimage.size()
        scale_x = width / size.width if size.width else 1
        scale_y = height / size.height if size.height else 1
        hotspot = cursor.hotSpot()
        xhot = round(hotspot.x * scale_x)
        yhot = round(hotspot.y * scale_y)
        # macOS does not expose a cursor identifier, so derive a stable serial
        # from the pixels and hotspot: identical cursors get the same serial,
        # which lets the client cache them:
        serial = crc32(pixels) ^ (xhot << 16) ^ yhot
        cursor_data = [0, 0, width, height, xhot, yhot, serial, pixels, b""]
        cursorlog("do_get_cursor_data() %ix%i cursor, hotspot %ix%i, serial=%#x",
                  width, height, xhot, yhot, serial)
        return (
            cursor_data,
            ((width, height), [(width, height), ]),
        )
