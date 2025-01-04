# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time
from ctypes import (
    get_last_error, windll,  # @UnresolvedImport
    Structure, byref, c_ubyte, c_char,
)
from io import BytesIO
from typing import Any
from PIL import Image

from xpra.log import Logger, consume_verbose_argv
from xpra.common import roundup
from xpra.util.env import envbool
from xpra.platform.win32 import constants as win32con
from xpra.platform.win32.gui import get_virtualscreenmetrics
from xpra.codecs.image import ImageWrapper

# user32:
from xpra.platform.win32.common import (
    GetDesktopWindow, GetWindowDC, ReleaseDC, DeleteDC,
    CreateCompatibleDC, CreateCompatibleBitmap,
    GetBitmapBits, SelectObject, DeleteObject,
    BitBlt, GetDeviceCaps,
    GetSystemPaletteEntries,
)

log = Logger("shadow", "win32")

NULLREGION = 1  # The region is empty.
SIMPLEREGION = 2  # The region is a single rectangle.
COMPLEXREGION = 3  # The region is more than a single rectangle.
REGION_CONSTS: dict[int, str] = {
    NULLREGION: "the region is empty",
    SIMPLEREGION: "the region is a single rectangle",
    COMPLEXREGION: "the region is more than a single rectangle",
}
DISABLE_DWM_COMPOSITION = envbool("XPRA_DISABLE_DWM_COMPOSITION", False)


class PALETTEENTRY(Structure):
    _fields_ = [
        ('peRed', c_ubyte),
        ('peGreen', c_ubyte),
        ('peBlue', c_ubyte),
        ('peFlags', c_ubyte),
    ]


DWM_EC_DISABLECOMPOSITION = 0
DWM_EC_ENABLECOMPOSITION = 1


def set_dwm_composition(value=DWM_EC_DISABLECOMPOSITION) -> bool:
    try:
        windll.dwmapi.DwmEnableComposition(value)
        log("DwmEnableComposition(%s) succeeded", value)
        return True
    except Exception as e:
        log.error("Error: cannot change dwm composition:")
        log.estr(e)
        return False


def get_desktop_bit_depth() -> int:
    desktop_wnd = GetDesktopWindow()
    dc = GetWindowDC(desktop_wnd)
    assert dc, "failed to get a drawing context from the desktop window %s" % desktop_wnd
    bit_depth = GetDeviceCaps(dc, win32con.BITSPIXEL)
    log("get_desktop_bit_depth()=%i", bit_depth)
    ReleaseDC(desktop_wnd, dc)
    return bit_depth


def get_palette(dc) -> list:
    count = GetSystemPaletteEntries(dc, 0, 0, None)
    log("palette size: %s", count)
    palette = []
    if count > 0:
        buf = (PALETTEENTRY * count)()
        r = GetSystemPaletteEntries(dc, 0, count, byref(buf))
        for i in range(min(count, r)):
            p = buf[i]
            # we expect 16-bit values, so bit-shift them:
            palette.append((p.peRed << 8, p.peGreen << 8, p.peBlue << 8))
    return palette


RGB_FORMATS = {
    32: "BGRX",
    30: "r210",
    24: "BGR",
    16: "BGR565",
    8: "RLE8",
}


class GDICapture:

    def __init__(self):
        self.metrics = None
        self.wnd, self.dc, self.memdc = None, None, None
        self.bit_depth = 32
        self.bitblt_err_time = 0.0
        self.disabled_dwm_composition = DISABLE_DWM_COMPOSITION and set_dwm_composition(DWM_EC_DISABLECOMPOSITION)

    def __repr__(self):
        return "GDICapture(%i-bits)" % self.bit_depth

    def get_info(self) -> dict[str, Any]:
        return {
            "type": "gdi",
            "depth": self.bit_depth,
        }

    def get_type(self) -> str:
        return "GDI"

    def refresh(self) -> bool:
        return True

    def clean(self) -> None:
        if self.disabled_dwm_composition:
            set_dwm_composition(DWM_EC_ENABLECOMPOSITION)
        self.clean_dc()

    def clean_dc(self) -> None:
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

    def get_capture_coords(self, x: int, y: int, width: int, height: int) -> tuple[int, int, int, int]:
        metrics = get_virtualscreenmetrics()
        if self.metrics is None or self.metrics != metrics:
            # new metrics, start from scratch:
            self.metrics = metrics
            self.clean()
        log("get_image%s metrics=%s", (x, y, width, height), metrics)
        dx, dy, dw, dh = metrics
        if width == 0:
            width = dw
        if height == 0:
            height = dh
        # clamp rectangle requested to the virtual desktop size:
        if x < dx:
            width -= x - dx
            x = dx
        if y < dy:
            height -= y - dy
            y = dy
        if width > dw:
            width = dw
        if height > dh:
            height = dh
        return x, y, width, height

    def get_image(self, x: int = 0, y: int = 0, width: int = 0, height: int = 0) -> ImageWrapper | None:
        start = time.time()
        x, y, width, height = self.get_capture_coords(x, y, width, height)
        if not self.dc:
            self.wnd = GetDesktopWindow()
            if not self.wnd:
                log.error("Error: cannot access the desktop window")
                log.error(" capturing the screen is not possible")
                return None
            self.dc = GetWindowDC(self.wnd)
            if not self.dc:
                log.error("Error: cannot get a drawing context")
                log.error(" capturing the screen is not possible")
                log.error(" desktop window=%#x", self.wnd)
                return None
            self.bit_depth = GetDeviceCaps(self.dc, win32con.BITSPIXEL)
            self.memdc = CreateCompatibleDC(self.dc)
            assert self.memdc, "failed to get a compatible drawing context from %s" % self.dc
        bitmap = CreateCompatibleBitmap(self.dc, width, height)
        if not bitmap:
            log.error("Error: failed to get a compatible bitmap")
            log.error(" from drawing context %#x with size %ix%i", self.dc, width, height)
            self.clean_dc()
            return None
        r = SelectObject(self.memdc, bitmap)
        if not r:
            log.error("Error: cannot select bitmap object")
            return None
        select_time = time.time()
        log("get_image up to SelectObject (%s) took %ims", REGION_CONSTS.get(r, r), (select_time - start) * 1000)
        try:
            if BitBlt(self.memdc, 0, 0, width, height, self.dc, x, y, win32con.SRCCOPY) == 0:
                e = get_last_error()
                # rate limit the error message:
                now = time.time()
                if now - self.bitblt_err_time > 10:
                    log.error("Error: failed to blit the screen, error %i", e)
                    self.bitblt_err_time = now
                return None
        except Exception as e:
            log("BitBlt error", exc_info=True)
            log.error("Error: cannot capture screen with BitBlt")
            log.estr(e)
            self.clean_dc()
            return None
        bitblt_time = time.time()
        log("get_image BitBlt took %ims", (bitblt_time - select_time) * 1000)
        rowstride = roundup(width * self.bit_depth // 8, 2)
        buf_size = rowstride * height
        # noinspection PyTypeChecker
        buftype = c_char * buf_size
        # noinspection PyCallingNonCallable
        buf = buftype()
        buf.value = b""
        log("GetBitmapBits(%#x, %#x, %#x)", bitmap, buf_size, byref(buf))
        r = GetBitmapBits(bitmap, buf_size, byref(buf))
        if not r:
            log.error("Error: failed to copy screen bitmap data")
            self.clean_dc()
            return None
        pixels: Any = buf
        if r != buf_size:
            log.warn("Warning: truncating pixel buffer, got %i bytes but expected %i", r, buf_size)
            pixels = buf[:r]
        log("get_image GetBitmapBits took %ims", (time.time() - bitblt_time) * 1000)
        DeleteObject(bitmap)
        assert pixels, "no pixels returned from GetBitmapBits"
        rgb_format = RGB_FORMATS.get(self.bit_depth)
        if not rgb_format:
            raise ValueError("unsupported bit depth: %s" % self.bit_depth)
        bpp = self.bit_depth // 8
        v = ImageWrapper(0, 0, width, height, pixels, rgb_format,
                         self.bit_depth, rowstride, bpp, planes=ImageWrapper.PACKED, thread_safe=True)
        if self.bit_depth == 8:
            palette = get_palette(self.dc)
            v.set_palette(palette)
        log("get_image%s=%s took %ims", (x, y, width, height), v, (time.time() - start) * 1000)
        return v

    def take_screenshot(self) -> tuple[int, int, str, int, bytes] | None:
        x, y, w, h = get_virtualscreenmetrics()
        image = self.get_image(x, y, w, h)
        if not image:
            return None
        assert image.get_width() == w and image.get_height() == h
        assert image.get_pixel_format() == "BGRX"
        img = Image.frombuffer("RGB", (w, h), image.get_pixels(), "raw", "BGRX", 0, 1)
        out = BytesIO()
        img.save(out, format="PNG")
        screenshot = (img.width, img.height, "png", img.width * 3, out.getvalue())
        out.close()
        return screenshot


def main(argv) -> int:
    from xpra.platform import program_context
    with program_context("Screen-Capture", "Screen Capture"):
        consume_verbose_argv(argv, "win32")
        capture = GDICapture()
        image = capture.take_screenshot()
        assert image, "failed to capture screenshot"
        from xpra.platform.paths import get_download_dir
        filename = os.path.join(get_download_dir(), "gdi-screenshot-%i.png" % time.time())
        with open(filename, "wb") as f:
            f.write(image[4])
        capture.clean()
    return 0


if __name__ == "__main__":
    import sys
    main(sys.argv)
