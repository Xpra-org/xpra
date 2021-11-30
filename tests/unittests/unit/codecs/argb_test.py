#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2016-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from time import monotonic

from xpra.os_util import hexstr
from xpra.codecs.argb import argb  #pylint: disable=no-name-in-module


def measure_fn(fn, data, *args):
    N = 100
    start = monotonic()
    for _ in range(N):
        r = fn(data, *args)
    end = monotonic()
    mps = len(data)*N//4/(end-start)//1024//1024
    print("%s: %iMPixels/s" % (fn, mps))
    return r

def cmp(inbytes, outbytes, fn, *args):
    datain = bytes(bytearray(inbytes))
    dataout = bytes(bytearray(outbytes))
    r = bytes(bytearray(fn(datain, *args)))
    print("%s(%s)=%s" % (fn, hexstr(datain), hexstr(r)))
    assert dataout==r, "expected %s but got %s" % (
        hexstr(dataout), hexstr(r))

class ARGBTest(unittest.TestCase):

    def test_r210_to_rgba(self):
        cmp((0xff, 0xfe, 0x7f, 0x7e),
            (0xf9, 0xff, 0xbf, 0x55),
            argb.r210_to_rgba, 1, 1, 4, 4,
            )
        cmp((0x17, 0x0f, 0x31, 0x8f),
            (0x3c, 0x10, 0xc5, 0xaa),
            argb.r210_to_rgba, 1, 1, 4, 4,
            )
        w = 1920
        h = 1080
        data = bytes(bytearray(w*h*4))
        measure_fn(argb.r210_to_rgba, data, w, h, w*4, w*4)

    def test_r210data_to_rgbx(self):
        cmp((0xff, 0xfe, 0x7f, 0x7e),
            (0xf9, 0xff, 0xbf, 0xff),
            argb.r210_to_rgbx, 1, 1, 4, 4,
            )
        cmp((0x17, 0x0f, 0x31, 0x8f),
            (0x3c, 0x10, 0xc5, 0xff),
            argb.r210_to_rgbx, 1, 1, 4, 4,
            )
        w = 1920
        h = 1080
        data = bytes(bytearray(w*h*4))
        measure_fn(argb.r210_to_rgbx, data, w, h, w*4, w*4)

    def test_argb_to_rgba(self):
        cmp((0xff, 0xfe, 0x7f, 0x7e),
            (0xfe, 0x7f, 0x7e, 0xff),
            argb.argb_to_rgba,
            )
        cmp((0x17, 0x0f, 0x31, 0x8f),
            (0x0f, 0x31, 0x8f, 0x17),
            argb.argb_to_rgba,
            )
        w = 1920
        h = 1080
        data = bytes(bytearray(w*h*4))
        measure_fn(argb.argb_to_rgba, data)

    def test_bgra_to_rgba(self):
        cmp((0xff, 0xfe, 0x7f, 0x7e),
            (0x7f, 0xfe, 0xff, 0x7e),
            argb.bgra_to_rgba,
            )
        cmp((0x17, 0x0f, 0x31, 0x8f),
            (0x31, 0x0f, 0x17, 0x8f),
            argb.bgra_to_rgba,
            )
        w = 1920
        h = 1080
        data = bytes(bytearray(w*h*4))
        measure_fn(argb.bgra_to_rgba, data)


def main():
    unittest.main()

if __name__ == '__main__':
    main()
