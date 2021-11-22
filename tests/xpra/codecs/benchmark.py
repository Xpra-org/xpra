#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from math import ceil
from time import monotonic

from xpra.util import csv
from xpra.codecs.image_wrapper import ImageWrapper

N = 10
Q = (1, 10, 50, 99, 100)

def main(argv):
    assert len(argv)>1, "specify images to benchmark"
    from xpra.codecs.loader import load_codecs, get_codec
    loaded = load_codecs(encoders=True, decoders=False, csc=False, video=False)
    print("loaded: %s" % (loaded,))
    for codec in loaded:
        print("%s : %s" % (codec, get_codec(codec)))

    from PIL import Image
    for f in argv[1:]:
        img = Image.open(f)
        pixel_format = "RGBA"
        if img.mode!=pixel_format:
            pixel_format = "RGB"
            img = img.convert(pixel_format)
        w, h = img.size
        rgb_data = img.tobytes("raw")
        stride = w * len(pixel_format)
        image = ImageWrapper(0, 0, w, h,
                             rgb_data, pixel_format, 32, stride,
                             planes=ImageWrapper.PACKED, thread_safe=True)
        print()
        print("%s : %s : %s" % (f, img, image))
        for warmup in (True, False):
            speed = 50
            for quality in Q:
                if not warmup:
                    print("quality = %i" % quality)
                for codec in loaded:
                    mod = get_codec(codec)
                    encodings = mod.get_encodings()
                    if not warmup:
                        print("  %s" % codec)
                    #print("%s" % (dir(mod), ))
                    for e in encodings:
                        start = monotonic()
                        sizes = []
                        n = 1 if warmup else N
                        for _ in range(n):
                            r = mod.encode(e, image, quality, speed)
                            cdata = r[1]
                            sizes.append(len(cdata))
                        end = monotonic()
                        if not warmup:
                            cratio = ceil(100*sum(sizes) / (w*h*len(pixel_format) * N))
                            mps = (w*h*N) / (end-start)
                            print("    %-16s : %3i%%    -    %i MPixels/s" % (e, cratio, mps//1024//1024))

if __name__ == '__main__':
    main(sys.argv)
