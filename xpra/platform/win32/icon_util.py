#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from ctypes import (
    WinError, get_last_error,  # @UnresolvedImport
    byref, c_void_p, sizeof, create_string_buffer, memmove,
    )

from xpra.platform.win32 import constants as win32con
from xpra.platform.win32.common import (
    ICONINFO, BITMAPV5HEADER,
    CreateIconIndirect,
    GetDC, ReleaseDC,
    CreateBitmap, CreateDIBSection,
    DeleteObject,
    )
from xpra.log import Logger
log = Logger("win32")

BI_RGB = 0
BI_BITFIELDS = 0x00000003


def image_to_ICONINFO(img, alpha=True):
    w, h = img.size
    if alpha and img.mode.find("A")>=0:   #ie: RGBA
        rgb_format = "BGRA"
    else:
        rgb_format = "BGR"
    rgb_data = img.tobytes("raw", rgb_format)
    return make_ICONINFO(w, h, rgb_data, rgb_format=rgb_format)

def make_ICONINFO(w, h, rgb_data, rgb_format="BGRA"):
    log("make_ICONINFO(%i, %i, %i bytes, %s)", w, h, len(rgb_data), rgb_format)
    bitmap = 0
    mask = 0
    try:
        bytes_per_pixel = len(rgb_format)
        bitmap = rgb_to_bitmap(rgb_data, bytes_per_pixel, w, h)
        log("rgb_to_bitmap(%i bytes, %i, %i, %i)=%s", len(rgb_data), bytes_per_pixel, w, h, bitmap)
        mask = CreateBitmap(w, h, 1, 1, None)
        log("CreateBitmap(%i, %i, 1, 1, None)=%#x", w, h, mask or 0)
        if not mask:
            raise WinError(get_last_error())
        iconinfo = ICONINFO()
        iconinfo.fIcon = True
        iconinfo.hbmMask = mask
        iconinfo.hbmColor = bitmap
        hicon = CreateIconIndirect(byref(iconinfo))
        log("CreateIconIndirect()=%#x", hicon or 0)
        if not hicon:
            raise WinError(get_last_error())
        return hicon
    except Exception:
        log.error("Error: failed to set tray icon", exc_info=True)
        return None
    finally:
        if mask:
            DeleteObject(mask)
        if bitmap:
            DeleteObject(bitmap)

def rgb_to_bitmap(rgb_data, bytes_per_pixel : int, w : int, h : int):
    log("rgb_to_bitmap%s", (rgb_data, bytes_per_pixel, w, h))
    assert bytes_per_pixel in (3, 4)        #only BGRA or BGR are supported
    assert w>0 and h>0
    header = BITMAPV5HEADER()
    header.bV5Size = sizeof(BITMAPV5HEADER)
    header.bV5Width = w
    header.bV5Height = -h
    header.bV5Planes = 1
    header.bV5BitCount = bytes_per_pixel*8
    header.bV5Compression = BI_RGB      #BI_BITFIELDS
    #header.bV5RedMask = 0x000000ff
    #header.bV5GreenMask = 0x0000ff00
    #header.bV5BlueMask = 0x00ff0000
    #header.bV5AlphaMask = 0xff000000
    hdc = 0
    try:
        hdc = GetDC(None)
        dataptr = c_void_p()
        log("GetDC()=%#x", hdc)
        bitmap = CreateDIBSection(hdc, byref(header), win32con.DIB_RGB_COLORS, byref(dataptr), None, 0)
    finally:
        if hdc:
            ReleaseDC(None, hdc)
    if not dataptr or not bitmap:
        raise WinError(get_last_error())
    log("CreateDIBSection(..) got bitmap=%#x, dataptr=%s", int(bitmap), dataptr)
    img_data = create_string_buffer(rgb_data)
    memmove(dataptr, byref(img_data), w*h*bytes_per_pixel)
    return bitmap
