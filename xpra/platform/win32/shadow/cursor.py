# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from ctypes import sizeof, byref, c_char
from ctypes.wintypes import MAX_PATH

from xpra.util.str_fn import strtobytes
from xpra.platform.win32 import constants as win32con
from xpra.log import Logger

# user32:
from xpra.platform.win32.common import (
    GetDC, CreateCompatibleDC, CreateCompatibleBitmap, SelectObject, DeleteObject,
    ReleaseDC, DeleteDC, DrawIconEx, GetBitmapBits,
    GetIconInfo, ICONINFO, Bitmap, GetIconInfoExW, ICONINFOEXW,
    GetObjectA,
)

log = Logger("cursor")

UINT_MAX = 2 ** 32 - 1


def monochrome_cursor_pixels(hbmMask) -> tuple[bytes, int, int] | None:
    """
    Convert the mask bitmap of a black and white cursor into `BGRA` pixels.

    These cursors have no colour bitmap: `hbmMask` is a 1-bit bitmap twice as tall
    as the cursor, holding the `AND` mask on top of the `XOR` mask.
    Combining both bits for each pixel gives:
        AND=0, XOR=0 : opaque black
        AND=0, XOR=1 : opaque white
        AND=1, XOR=0 : transparent
        AND=1, XOR=1 : inverted screen content
    We have no screen content to invert, so those pixels are painted black:
    this is what keeps the text `I-beam` cursor visible on light backgrounds.
    """
    bm = Bitmap()
    if not GetObjectA(hbmMask, sizeof(Bitmap), byref(bm)):
        raise OSError()  # @UndefinedVariable
    log("cursor mask bitmap: width=%i, height=%i, width bytes=%i, planes=%i, bits pixel=%i",
        bm.bmWidth, bm.bmHeight, bm.bmWidthBytes, bm.bmPlanes, bm.bmBitsPixel)
    if bm.bmBitsPixel != 1 or bm.bmPlanes != 1 or bm.bmHeight % 2 or bm.bmWidth <= 0:
        log.warn("Warning: unsupported black and white cursor mask")
        log.warn(" %ix%i with %i plane(s) and %i bit(s) per pixel",
                 bm.bmWidth, bm.bmHeight, bm.bmPlanes, bm.bmBitsPixel)
        return None
    w = bm.bmWidth
    h = bm.bmHeight // 2
    stride = bm.bmWidthBytes
    buf_size = stride * bm.bmHeight
    buftype = c_char * buf_size
    # noinspection PyCallingNonCallable
    buf = buftype()
    r = GetBitmapBits(hbmMask, buf_size, byref(buf))
    if r != buf_size:
        log.warn("Warning: invalid cursor mask size, got %i bytes but expected %i", r, buf_size)
        return None
    mask = buf.raw
    # zeroed, which is already what the transparent pixels need:
    pixels = bytearray(w * h * 4)
    for row in range(h):
        and_offset = row * stride
        xor_offset = (row + h) * stride
        for col in range(w):
            bit = 0x80 >> (col & 0x7)
            byte = col >> 3
            xor_bit = mask[xor_offset + byte] & bit
            if mask[and_offset + byte] & bit:
                if not xor_bit:
                    continue                        # transparent
                value = 0                           # inverted: painted black
            else:
                value = 0xFF if xor_bit else 0      # white or black
            i = (row * w + col) * 4
            pixels[i] = pixels[i + 1] = pixels[i + 2] = value
            pixels[i + 3] = 0xFF
    return bytes(pixels), w, h


def get_cursor_data(hCursor) -> list | None:
    # w, h = get_fixed_cursor_size()
    if not hCursor:
        return None
    dc = None
    memdc = None
    bitmap = None
    old_handle = None
    # `GetIconInfo` and `GetIconInfoExW` both create `hbmMask` and `hbmColor`
    # bitmaps which belong to us: collect them so that we can delete them below,
    # otherwise we leak two GDI objects every time the cursor shape changes
    icon_bitmaps: list[int] = []
    try:
        ii = ICONINFO()
        if not GetIconInfo(hCursor, byref(ii)):
            raise OSError()  # @UndefinedVariable
        icon_bitmaps += [handle for handle in (ii.hbmColor, ii.hbmMask) if handle]
        x = ii.xHotspot
        y = ii.yHotspot
        log("get_cursor_data(%#x) hotspot at %ix%i, hbmColor=%#x, hbmMask=%#x",
            hCursor, x, y, ii.hbmColor or 0, ii.hbmMask or 0)
        iie = ICONINFOEXW()
        iie.cbSize = sizeof(ICONINFOEXW)
        if not GetIconInfoExW(hCursor, byref(iie)):
            raise OSError()  # @UndefinedVariable
        icon_bitmaps += [handle for handle in (iie.hbmColor, iie.hbmMask) if handle]
        name = iie.szResName[:MAX_PATH]
        log("wResID=%#x, sxModName=%s, szResName=%s", iie.wResID, iie.sxModName[:MAX_PATH], name)
        if not ii.hbmColor:
            # black and white cursor: the shape is encoded in the mask bitmap
            mono = monochrome_cursor_pixels(ii.hbmMask)
            if not mono:
                return None
            mono_pixels, mono_w, mono_h = mono
            return [0, 0, mono_w, mono_h, x, y, hCursor, mono_pixels, strtobytes(name)]
        bm = Bitmap()
        if not GetObjectA(ii.hbmColor, sizeof(Bitmap), byref(bm)):
            raise OSError()  # @UndefinedVariable
        log("cursor bitmap: type=%i, width=%i, height=%i, width bytes=%i, planes=%i, bits pixel=%i, bits=%#x",
            bm.bmType, bm.bmWidth, bm.bmHeight, bm.bmWidthBytes, bm.bmPlanes, bm.bmBitsPixel, bm.bmBits or 0)
        w = bm.bmWidth
        h = bm.bmHeight
        dc = GetDC(None)
        assert dc, "failed to get a drawing context"
        memdc = CreateCompatibleDC(dc)
        assert memdc, "failed to get a compatible drawing context from %s" % dc
        bitmap = CreateCompatibleBitmap(dc, w, h)
        assert bitmap, "failed to get a compatible bitmap from %s" % dc
        old_handle = SelectObject(memdc, bitmap)

        # check if icon is animated:
        if not DrawIconEx(memdc, 0, 0, hCursor, w, h, UINT_MAX, 0, 0):
            log("cursor is animated!")

        # if not DrawIcon(memdc, 0, 0, hCursor):
        if not DrawIconEx(memdc, 0, 0, hCursor, w, h, 0, 0, win32con.DI_NORMAL):
            raise OSError()  # @UndefinedVariable

        buf_size = bm.bmWidthBytes * h
        buftype = c_char * buf_size
        # noinspection PyCallingNonCallable
        buf = buftype()
        buf.value = b""
        r = GetBitmapBits(bitmap, buf_size, byref(buf))
        log("get_cursor_data(%#x) GetBitmapBits(%#x, %#x, %#x)=%i", hCursor, bitmap, buf_size, byref(buf), r)
        if not r:
            log.error("Error: failed to copy screen bitmap data")
            return None
        elif r != buf_size:
            log.warn("Warning: invalid cursor buffer size, got %i bytes but expected %i", r, buf_size)
            return None
        else:
            # 32-bit data:
            pixels = bytearray(strtobytes(buf.raw))
            has_alpha = False
            has_pixels = False
            for i in range(len(pixels) // 4):
                has_pixels = has_pixels or pixels[i * 4] != 0 or pixels[i * 4 + 1] != 0 or pixels[i * 4 + 2] != 0
                has_alpha = has_alpha or pixels[i * 4 + 3] != 0
                if has_pixels and has_alpha:
                    break
            if has_pixels and not has_alpha:
                # generate missing alpha - don't ask me why
                for i in range(len(pixels) // 4):
                    if pixels[i * 4] != 0 or pixels[i * 4 + 1] != 0 or pixels[i * 4 + 2] != 0:
                        pixels[i * 4 + 3] = 0xff
        return [0, 0, w, h, x, y, hCursor, bytes(pixels), strtobytes(name)]
    except Exception as e:
        log("get_cursor_data(%#x)", hCursor, exc_info=True)
        log.error("Error: failed to grab cursor:")
        log.estr(e)
        return None
    finally:
        if old_handle:
            SelectObject(memdc, old_handle)
        if bitmap:
            DeleteObject(bitmap)
        if memdc:
            DeleteDC(memdc)
        if dc:
            ReleaseDC(None, dc)
        for handle in icon_bitmaps:
            DeleteObject(handle)
