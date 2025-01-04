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


def get_cursor_data(hCursor) -> list | None:
    # w, h = get_fixed_cursor_size()
    if not hCursor:
        return None
    dc = None
    memdc = None
    bitmap = None
    old_handle = None
    try:
        ii = ICONINFO()
        ii.cbSize = sizeof(ICONINFO)
        if not GetIconInfo(hCursor, byref(ii)):
            raise OSError()  # @UndefinedVariable
        x = ii.xHotspot
        y = ii.yHotspot
        log("get_cursor_data(%#x) hotspot at %ix%i, hbmColor=%#x, hbmMask=%#x",
            hCursor, x, y, ii.hbmColor or 0, ii.hbmMask or 0)
        if not ii.hbmColor:
            # FIXME: we don't handle black and white cursors
            return None
        iie = ICONINFOEXW()
        iie.cbSize = sizeof(ICONINFOEXW)
        if not GetIconInfoExW(hCursor, byref(iie)):
            raise OSError()  # @UndefinedVariable
        name = iie.szResName[:MAX_PATH]
        log("wResID=%#x, sxModName=%s, szResName=%s", iie.wResID, iie.sxModName[:MAX_PATH], name)
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
