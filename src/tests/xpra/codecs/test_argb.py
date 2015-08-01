#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time

from tests.xpra.codecs.test_codec import get_source_data
from xpra.codecs.argb.argb import argb_to_rgba, argb_to_rgb, bgra_to_rgb, bgra_to_rgba, unpremultiply_argb_in_place, unpremultiply_argb #@UnresolvedImport

N = 10

def test_argb():
    print("test_argb()")
    #1 frame of 4k 32bpp:
    pixels = 1024*1024*4
    d = get_source_data(pixels*4)
    for fn in (argb_to_rgba, argb_to_rgb, bgra_to_rgb, bgra_to_rgba):
        start = time.time()
        for _ in range(N):
            fn(d)
        end = time.time()
        elapsed = end-start
        print("%40s took %5ims: %5i MPixels/s" % (fn, elapsed*1000//N, pixels*N/1024/1024/elapsed))

def test_premultiply():
    pass

def main():
    test_argb()
    test_premultiply()


if __name__ == "__main__":
    main()
