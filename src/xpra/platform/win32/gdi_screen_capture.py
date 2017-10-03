# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2012-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import ctypes
from PIL import Image

from xpra.log import Logger
from xpra.util import envbool, roundup
log = Logger("shadow", "win32")

from xpra.os_util import BytesIOClass
from xpra.platform.win32 import constants as win32con
from xpra.platform.win32.gui import get_virtualscreenmetrics
from xpra.codecs.image_wrapper import ImageWrapper

#user32:
from xpra.platform.win32.common import (
    GetDesktopWindow, GetWindowDC, ReleaseDC, DeleteDC,
    CreateCompatibleDC, CreateCompatibleBitmap,
    GetBitmapBits, SelectObject, DeleteObject,
    BitBlt, GetDeviceCaps,
    GetSystemPaletteEntries)

NULLREGION = 1      #The region is empty.
SIMPLEREGION = 2    #The region is a single rectangle.
COMPLEXREGION = 3   #The region is more than a single rectangle.
REGION_CONSTS = {
                NULLREGION      : "the region is empty",
                SIMPLEREGION    : "the region is a single rectangle",
                COMPLEXREGION   : "the region is more than a single rectangle",
                }
DISABLE_DWM_COMPOSITION = True
#no composition on XP, don't bother trying:
try:
    from sys import getwindowsversion       #@UnresolvedImport
    if getwindowsversion().major<6:
        DISABLE_DWM_COMPOSITION = False
except:
    pass
DISABLE_DWM_COMPOSITION = envbool("XPRA_DISABLE_DWM_COMPOSITION", DISABLE_DWM_COMPOSITION)

class PALETTEENTRY(ctypes.Structure):
    _fields_ = [
        ('peRed',   ctypes.c_ubyte),
        ('peGreen', ctypes.c_ubyte),
        ('peBlue',  ctypes.c_ubyte),
        ('peFlags', ctypes.c_ubyte),
        ]

DWM_EC_DISABLECOMPOSITION = 0
DWM_EC_ENABLECOMPOSITION = 1
def set_dwm_composition(value=DWM_EC_DISABLECOMPOSITION):
    try:
        from ctypes import windll
        windll.dwmapi.DwmEnableComposition(value)
        log("DwmEnableComposition(%s) succeeded", value)
        return True
    except Exception as e:
        log.error("Error: cannot change dwm composition:")
        log.error(" %s", e)
        return False

def get_desktop_bit_depth():
    desktop_wnd = GetDesktopWindow()
    dc = GetWindowDC(desktop_wnd)
    assert dc, "failed to get a drawing context from the desktop window %s" % desktop_wnd
    bit_depth = GetDeviceCaps(dc, win32con.BITSPIXEL)
    log("get_desktop_bit_depth()=%i", bit_depth)
    ReleaseDC(desktop_wnd, dc)
    return bit_depth


class GDICapture(object):

    def __init__(self):
        self.metrics = None
        self.wnd, self.dc, self.memdc, self.bitmap = None, None, None, None
        self.bit_depth = 32
        self.bitblt_err_time = 0
        self.disabled_dwm_composition = DISABLE_DWM_COMPOSITION and set_dwm_composition(DWM_EC_DISABLECOMPOSITION)

    def __repr__(self):
        return "GDICapture(%i-bits)" % self.bit_depth

    def get_info(self):
        return {
            "type"  : "gdi",
            "depth" : self.bit_depth,
            }

    def clean(self):
        if self.disabled_dwm_composition:
            set_dwm_composition(DWM_EC_ENABLECOMPOSITION)
        bitmap = self.bitmap
        if bitmap:
            self.bitmap = None
            DeleteObject(bitmap)
        dc = self.dc
        wnd = self.wnd
        if dc and wnd:
            self.dc = None
            self.wnd = None
            ReleaseDC(wnd, dc)
        memdc = self.memdc
        if memdc:
            self.memdc = None
            DeleteDC(memdc)

    def get_image(self, x=0, y=0, width=0, height=0):
        start = time.time()
        metrics = get_virtualscreenmetrics()
        if self.metrics is None or self.metrics!=metrics:
            #new metrics, start from scratch:
            self.metrics = metrics
            self.clean()
        dx, dy, dw, dh = metrics
        if width==0:
            width = dw
        if height==0:
            height = dh
        #clamp rectangle requested to the virtual desktop size:
        if x<dx:
            width -= x-dx
            x = dx
        if y<dy:
            height -= y-dy
            y = dy
        if width>dw:
            width = dw
        if height>dh:
            height = dh
        if not self.dc:
            self.wnd = GetDesktopWindow()
            self.dc = GetWindowDC(self.wnd)
            assert self.dc, "failed to get a drawing context from the desktop window %s" % self.wnd
            self.bit_depth = GetDeviceCaps(self.dc, win32con.BITSPIXEL)
            self.memdc = CreateCompatibleDC(self.dc)
            assert self.memdc, "failed to get a compatible drawing context from %s" % self.dc
            self.bitmap = CreateCompatibleBitmap(self.dc, width, height)
            assert self.bitmap, "failed to get a compatible bitmap from %s" % self.dc
        r = SelectObject(self.memdc, self.bitmap)
        if r==0:
            log.error("Error: cannot select bitmap object")
            return None
        select_time = time.time()
        log("get_image up to SelectObject (%s) took %ims", REGION_CONSTS.get(r, r), (select_time-start)*1000)
        try:
            if BitBlt(self.memdc, 0, 0, width, height, self.dc, x, y, win32con.SRCCOPY)==0:
                e = ctypes.get_last_error()
                #rate limit the error message:
                now = time.time()
                if now-self.bitblt_err_time>10:
                    log.error("Error: failed to blit the screen, error %i", e)
                    self.bitblt_err_time = now
                return None
        except Exception as e:
            log("BitBlt error", exc_info=True)
            log.error("Error: cannot capture screen")
            log.error(" %s", e)
            return None
        bitblt_time = time.time()
        log("get_image BitBlt took %ims", (bitblt_time-select_time)*1000)
        rowstride = roundup(width*self.bit_depth//8, 2)
        buf_size = rowstride*height
        pixels = ctypes.create_string_buffer(b"", buf_size)
        log("GetBitmapBits(%#x, %#x, %#x)", self.bitmap, buf_size, ctypes.addressof(pixels))
        r = GetBitmapBits(self.bitmap, buf_size, ctypes.byref(pixels))
        if r==0:
            log.error("Error: failed to copy screen bitmap data")
            return None
        if r!=buf_size:
            log.warn("Warning: truncating pixel buffer, got %i bytes but expected %i", r, buf_size)
            pixels = pixels[:r]
        log("get_image GetBitmapBits took %ims", (time.time()-bitblt_time)*1000)
        assert pixels, "no pixels returned from GetBitmapBits"
        if self.bit_depth==32:
            rgb_format = "BGRX"
        elif self.bit_depth==30:
            rgb_format = "r210"
        elif self.bit_depth==24:
            rgb_format = "BGR"
        elif self.bit_depth==16:
            rgb_format = "BGR565"
        elif self.bit_depth==8:
            rgb_format = "RLE8"
        else:
            raise Exception("unsupported bit depth: %s" % self.bit_depth)
        bpp = self.bit_depth//8
        v = ImageWrapper(x, y, width, height, pixels, rgb_format, self.bit_depth, rowstride, bpp, planes=ImageWrapper.PACKED, thread_safe=True)
        if self.bit_depth==8:
            count = GetSystemPaletteEntries(self.dc, 0, 0, None)
            log("palette size: %s", count)
            palette = []
            if count>0:
                buf = (PALETTEENTRY*count)()
                r = GetSystemPaletteEntries(self.dc, 0, count, ctypes.byref(buf))
                #we expect 16-bit values, so bit-shift them:
                for p in buf:
                    palette.append((p.peRed<<8, p.peGreen<<8, p.peBlue<<8))
            v.set_palette(palette)
        log("get_image%s=%s took %ims", (x, y, width, height), v, (time.time()-start)*1000)
        return v

    def take_screenshot(self):
        x, y, w, h = get_virtualscreenmetrics()
        image = self.get_image(x, y, w, h)
        if not image:
            return None
        assert image.get_width()==w and image.get_height()==h
        assert image.get_pixel_format()=="BGRX"
        img = Image.frombuffer("RGB", (w, h), image.get_pixels(), "raw", "BGRX", 0, 1)
        out = BytesIOClass()
        img.save(out, format="PNG")
        screenshot = (img.width, img.height, "png", img.width*3, out.getvalue())
        out.close()
        return screenshot

def main():
    import sys
    import os.path
    if "-v" in sys.argv or "--verbose" in sys.argv:
        log.enable_debug()

    from xpra.platform import program_context
    with program_context("Screen-Capture", "Screen Capture"):
        capture = GDICapture()
        image = capture.take_screenshot()
        from xpra.platform.paths import get_download_dir
        filename = os.path.join(get_download_dir(), "gdi-screenshot-%i.png" % time.time())
        with open(filename, 'wb') as f:
            f.write(image[4])

if __name__ == "__main__":
    main()
