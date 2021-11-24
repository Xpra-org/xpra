#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from time import monotonic

from xpra.codecs.argb.argb import bgrx_to_rgb


def measure_fn(fn, data):
    N = 100
    start = monotonic()
    for _ in range(N):
        r = fn(data)
    end = monotonic()
    mps = len(data)*N//4/(end-start)//1024//1024
    print("%s: %iMPixels/s" % (fn, mps))
    return r


def main(argv):
    from PIL import Image
    for f in argv[1:]:
        img = Image.open(f)
        img.show()
        if img.mode=="RGB":
            img = img.convert("RGBA")
        if img.mode=="RGBA":
            rgb_data = img.tobytes("raw")
            data = measure_fn(bgrx_to_rgb, rgb_data)
            w, h = img.size
            reloaded = Image.frombuffer("RGB", (w, h), data.tobytes(), "raw")
            reloaded.show()
        else:
            print("file '%s' is not RGBA" % f)

if __name__ == '__main__':
    main(sys.argv)
