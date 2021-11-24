#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from math import ceil
from time import monotonic

from xpra.util import csv
from xpra.codecs.argb.argb import argb_swap
from xpra.codecs.image_wrapper import ImageWrapper

N = 10
#Q = (20, 99)
Q = (1, 10, 50, 99, 100)

def main(argv):
    assert len(argv)>1, "specify images to benchmark"
    from xpra.net import compression
    compression.init_all()
    from xpra.codecs.loader import load_codecs, get_codec
    loaded = load_codecs(encoders=True, decoders=False, csc=False, video=False)
    print("loaded: %s" % csv(loaded))
    for codec in loaded:
        print("%s : %s" % (codec, get_codec(codec)))

    from PIL import Image
    for f in argv[1:]:
        img = Image.open(f)
        if img.mode not in ("RGBA", "RGB"):
            img = img.convert("RGB")
        pixel_format = img.mode
        w, h = img.size
        rgb_data = img.tobytes("raw")
        stride = w * len(pixel_format)
        print()
        print("%s : %s" % (f, img))
        for warmup in (True, False):
            speed = 50
            for quality in Q:
                if not warmup:
                    print()
                    print("quality = %i" % quality)
                for codec in loaded:
                    mod = get_codec(codec)
                    encodings = mod.get_encodings()
                    if not warmup:
                        print("  %s : %s" % (codec, encodings))
                    #print("%s" % (dir(mod), ))
                    for e in encodings:
                        image = ImageWrapper(0, 0, w, h,
                                             rgb_data, pixel_format, len(pixel_format)*8, stride,
                                             planes=ImageWrapper.PACKED, thread_safe=True)
                        sizes = []
                        n = 1 if warmup else N
                        options = {
                            "quality"       : quality,
                            "speed"         : speed,
                            "rgb_formats"   : ("BGRX", "BGRA", "RGBA", "RGBX", "RGB", "BGR"),
                            "zlib"          : True,
                            "lz4"           : True,
                            "alpha"         : True,
                            }
                        client_options = {}
                        start = monotonic()
                        for _ in range(n):
                            try:
                                r = mod.encode(e, image, options)
                            except Exception:
                                print("error on %s.%s" % (mod, mod.encode))
                                raise
                            if not r:
                                print("error: no data for %s encoding %s as %r" % (codec, image, e))
                                continue
                            cdata = r[1]
                            client_options = r[2]
                            sizes.append(len(cdata))
                        end = monotonic()
                        if not warmup:
                            cratio = ceil(100*sum(sizes) / (w*h*len(pixel_format) * N))
                            mps = (w*h*N) / (end-start)
                            print("    %-16s : %3i%%    -    %7i MPixels/s,    %s" % (
                                e, cratio, mps//1024//1024, client_options))

if __name__ == '__main__':
    main(sys.argv)
