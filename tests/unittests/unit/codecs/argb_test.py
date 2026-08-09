#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2016-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from time import monotonic

from xpra.os_util import hexstr
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.codecs.argb.argb import (     # pylint: disable=no-name-in-module
    r210_to_rgba, r210_to_rgbx, argb_to_rgba, bgra_to_rgba,
    rgb_to_bgrx, bgrx_to_rgb, rgbx_to_rgb, bgrx_to_l, bgra_to_la, rgb_to_l, bgr_to_l,
    argb_swap,
)


def measure_fn(fn, data, *args):
    N = 10
    start = monotonic()
    for _ in range(N):
        r = fn(data, *args)
    end = monotonic()
    mps = len(data)*N//4/(end-start)//1024//1024
    print(f"{fn}: {mps} MPixels/s")
    return r

def cmp(inbytes, outbytes, fn, *args):
    datain = bytes(bytearray(inbytes))
    dataout = bytes(bytearray(outbytes))
    r = bytes(bytearray(fn(datain, *args)))
    assert dataout==r, f"expected {hexstr(dataout)} but got {hexstr(r)}"

class ARGBTest(unittest.TestCase):

    def test_r210_to_rgba(self):
        cmp((0xff, 0xfe, 0x7f, 0x7e),
            (0xf9, 0xff, 0xbf, 0x55),
            r210_to_rgba, 1, 1, 4, 4,
            )
        cmp((0x17, 0x0f, 0x31, 0x8f),
            (0x3c, 0x10, 0xc5, 0xaa),
            r210_to_rgba, 1, 1, 4, 4,
            )
        w = 1920
        h = 1080
        data = bytes(bytearray(w*h*4))
        measure_fn(r210_to_rgba, data, w, h, w*4, w*4)

    def test_r210data_to_rgbx(self):
        cmp((0xff, 0xfe, 0x7f, 0x7e),
            (0xf9, 0xff, 0xbf, 0xff),
            r210_to_rgbx, 1, 1, 4, 4,
            )
        cmp((0x17, 0x0f, 0x31, 0x8f),
            (0x3c, 0x10, 0xc5, 0xff),
            r210_to_rgbx, 1, 1, 4, 4,
            )
        w = 1920
        h = 1080
        data = bytes(bytearray(w*h*4))
        measure_fn(r210_to_rgbx, data, w, h, w*4, w*4)

    def test_argb_to_rgba(self):
        cmp((0xff, 0xfe, 0x7f, 0x7e),
            (0xfe, 0x7f, 0x7e, 0xff),
            argb_to_rgba,
            )
        cmp((0x17, 0x0f, 0x31, 0x8f),
            (0x0f, 0x31, 0x8f, 0x17),
            argb_to_rgba,
            )
        w = 1920
        h = 1080
        data = bytes(bytearray(w*h*4))
        measure_fn(argb_to_rgba, data)

    def test_bgra_to_rgba(self):
        cmp((0xff, 0xfe, 0x7f, 0x7e),
            (0x7f, 0xfe, 0xff, 0x7e),
            bgra_to_rgba,
            )
        cmp((0x17, 0x0f, 0x31, 0x8f),
            (0x31, 0x0f, 0x17, 0x8f),
            bgra_to_rgba,
            )
        w = 1920
        h = 1080
        data = bytes(bytearray(w*h*4))
        measure_fn(bgra_to_rgba, data)

    def test_rgb_to_bgrx(self):
        # the red and blue bytes must be swapped,
        # and the padding byte must be opaque so the data is also valid as `BGRA`:
        cmp((0x11, 0x22, 0x33),
            (0x33, 0x22, 0x11, 0xff),
            rgb_to_bgrx,
            )
        # more than one pixel:
        cmp((0x11, 0x22, 0x33) * 3,
            (0x33, 0x22, 0x11, 0xff) * 3,
            rgb_to_bgrx,
            )
        # `bgrx_to_rgb` is the inverse operation:
        cmp((0x33, 0x22, 0x11, 0x8f),
            (0x11, 0x22, 0x33),
            bgrx_to_rgb,
            )
        cmp((0x33, 0x22, 0x11, 0x8f) * 3,
            (0x11, 0x22, 0x33) * 3,
            bgrx_to_rgb,
            )

    def test_rgbx_to_rgb(self):
        # the red byte already comes first: only the 4th byte is dropped
        cmp((0x11, 0x22, 0x33, 0x8f),
            (0x11, 0x22, 0x33),
            rgbx_to_rgb,
            )
        cmp((0x11, 0x22, 0x33, 0x8f) * 3,
            (0x11, 0x22, 0x33) * 3,
            rgbx_to_rgb,
            )

    def test_to_luminance(self):
        # the weights are 3/8 for red, 4/8 for green and 1/8 for blue:
        r, g, b = 0x11, 0x22, 0x33
        l = (r * 3 + b + g * 4) >> 3
        n = 10
        cmp((b, g, r, 0x8f) * n, (l, ) * n, bgrx_to_l)
        cmp((b, g, r, 0x8f) * n, (l, 0x8f) * n, bgra_to_la)
        cmp((r, g, b) * n, (l, ) * n, rgb_to_l)
        cmp((b, g, r) * n, (l, ) * n, bgr_to_l)
        # green is the brightest, blue the darkest:
        for fn, red, green, blue in (
            (bgrx_to_l, (0, 0, 0xff, 0), (0, 0xff, 0, 0), (0xff, 0, 0, 0)),
            (rgb_to_l, (0xff, 0, 0), (0, 0xff, 0), (0, 0, 0xff)),
            (bgr_to_l, (0, 0, 0xff), (0, 0xff, 0), (0xff, 0, 0)),
        ):
            values = tuple(fn(bytes(bytearray(pixel)))[0] for pixel in (red, green, blue))
            assert values[1] > values[0] > values[2], f"{fn}: green > red > blue, but got {values}"


class ARGBSwapTest(unittest.TestCase):
    """`argb_swap` must update the pixel format, the pixels and the rowstride consistently"""

    WIDTH = 2
    HEIGHT = 2

    def swap(self, pixel_format, pixel, rgb_formats, transparency=True):
        bpp = len(pixel)
        rowstride = self.WIDTH * bpp
        pixels = bytes(bytearray(pixel)) * (self.WIDTH * self.HEIGHT)
        image = ImageWrapper(0, 0, self.WIDTH, self.HEIGHT, memoryview(pixels), pixel_format, 24, rowstride, planes=ImageWrapper.PACKED)
        r = argb_swap(image, rgb_formats, transparency)
        assert r is True, f"argb_swap failed for {pixel_format} to one of {rgb_formats}"
        return image

    def check(self, pixel_format, pixel, rgb_formats, out_format, out_pixel, transparency=True):
        image = self.swap(pixel_format, pixel, rgb_formats, transparency)
        self.assertEqual(image.get_pixel_format(), out_format)
        pixels = bytes(bytearray(image.get_pixels()))
        self.assertEqual(hexstr(pixels), hexstr(bytes(bytearray(out_pixel)) * (self.WIDTH * self.HEIGHT)))
        # the rowstride must match the new number of bytes per pixel:
        self.assertEqual(image.get_rowstride(), self.WIDTH * len(out_pixel),
                         f"invalid rowstride for {out_format}")

    def test_rgbx_to_rgb(self):
        # the red byte already comes first, only the 4th byte is dropped:
        self.check("RGBX", (0x11, 0x22, 0x33, 0x8f), ("RGB", ), "RGB", (0x11, 0x22, 0x33))
        self.check("RGBA", (0x11, 0x22, 0x33, 0x8f), ("RGB", ), "RGB", (0x11, 0x22, 0x33))

    def test_rgba_to_bgra(self):
        # both formats use 4 bytes per pixel, so the rowstride is unchanged:
        self.check("RGBA", (0x11, 0x22, 0x33, 0x8f), ("BGRA", ), "BGRA", (0x33, 0x22, 0x11, 0x8f))

    def test_bgrx_to_rgb(self):
        self.check("BGRX", (0x33, 0x22, 0x11, 0x8f), ("RGB", ), "RGB", (0x11, 0x22, 0x33))
        self.check("BGRA", (0x33, 0x22, 0x11, 0x8f), ("RGB", ), "RGB", (0x11, 0x22, 0x33))

    def test_bgra_to_rgba(self):
        self.check("BGRA", (0x33, 0x22, 0x11, 0x8f), ("RGBA", ), "RGBA", (0x11, 0x22, 0x33, 0x8f))

    def test_bgra_to_rgbx(self):
        self.check("BGRA", (0x33, 0x22, 0x11, 0x8f), ("RGBX", ), "RGBX", (0x11, 0x22, 0x33, 0xff))

    def test_argb_to_rgb(self):
        self.check("ARGB", (0x8f, 0x11, 0x22, 0x33), ("RGB", ), "RGB", (0x11, 0x22, 0x33))
        self.check("ARGB", (0x8f, 0x11, 0x22, 0x33), ("RGBA", ), "RGBA", (0x11, 0x22, 0x33, 0x8f))

    def test_rgb_to_bgrx(self):
        self.check("RGB", (0x11, 0x22, 0x33), ("BGRX", ), "BGRX", (0x33, 0x22, 0x11, 0xff))

    def test_to_luminance(self):
        r, g, b = 0x11, 0x22, 0x33
        l = (r * 3 + b + g * 4) >> 3
        self.check("BGRX", (b, g, r, 0x8f), ("L", ), "L", (l, ))
        self.check("BGRA", (b, g, r, 0x8f), ("LA", ), "LA", (l, 0x8f))

    def test_unsupported_format(self):
        from unit.test_util import LoggerSilencer
        from xpra.codecs.argb import argb  # pylint: disable=no-name-in-module
        pixels = memoryview(bytes(bytearray(16)))
        image = ImageWrapper(0, 0, 2, 2, pixels, "BGRX", 24, 8, planes=ImageWrapper.PACKED)
        with LoggerSilencer(argb):
            self.assertFalse(argb_swap(image, ("YUV420P", )))


def main():
    unittest.main()

if __name__ == "__main__":
    main()
