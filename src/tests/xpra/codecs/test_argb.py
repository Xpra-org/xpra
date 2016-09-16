#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time

from tests.xpra.codecs.test_codec import get_source_data
from xpra.codecs.argb.argb import argb_to_rgba, argb_to_rgb, bgra_to_rgb, bgra_to_rgba, unpremultiply_argb_in_place, unpremultiply_argb, r210_to_rgba, r210_to_rgb #@UnresolvedImport

N = 10

def _test_functions(*fns):
    #1 frame of 4k 32bpp:
    pixels = 1024*1024*4
    d = get_source_data(pixels*4)
    for fn in fns:
        start = time.time()
        for _ in range(N):
            fn(d)
        end = time.time()
        elapsed = end-start
        print("%60s took %5ims: %5i MPixels/s" % (fn, elapsed*1000//N, pixels*N/1024/1024/elapsed))

def test_premultiply():
    print("test_premultiply()")
    _test_functions(unpremultiply_argb_in_place, unpremultiply_argb)

def test_argb():
    print("test_argb()")
    #1 frame of 4k 32bpp:
    _test_functions(argb_to_rgba, argb_to_rgb, bgra_to_rgb, bgra_to_rgba, r210_to_rgba, r210_to_rgb)

def main():
    test_premultiply()
    test_argb()


if __name__ == "__main__":
    main()
