#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from time import monotonic

from xpra.util.str_fn import hexstr
from xpra.codecs.argb.argb import r210_to_rgba, r210_to_rgbx, argb_to_rgba, bgra_to_rgba     # pylint: disable=no-name-in-module


def measure_fn(fn, data, *args):
    N = 10
    start = monotonic()
    for _ in range(N):
        fn(data, *args)
    end = monotonic()
    mps = len(data)*N//4/(end-start)//1024//1024
    print(f"{fn}: {mps} MPixels/s")


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


def main():
    unittest.main()


if __name__ == "__main__":
    main()
