#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from time import monotonic

from xpra.codecs.image_wrapper import ImageWrapper

N = 10

def main(argv):
    assert len(argv)>1, "specify images to benchmark"
    from xpra.net import compression
    compression.init_all()
    from xpra.codecs.loader import load_codec, get_codec

    FORMAT = "png"
    CODECS = ("enc_spng", "enc_pillow")
    for codec in CODECS:
        load_codec(codec)

    from PIL import Image
    for f in argv[1:]:
        img = Image.open(f)
        if img.mode not in ("RGBA", "RGB"):
            img = img.convert("RGB")
        #img.show()
        pixel_format = img.mode
        w, h = img.size
        rgb_data = img.tobytes("raw")
        stride = w * len(pixel_format)
        print("%s : %s" % (f, img))
        image = ImageWrapper(0, 0, w, h,
                             rgb_data, pixel_format, len(pixel_format)*8, stride,
                             planes=ImageWrapper.PACKED, thread_safe=True)
        for codec in CODECS:
            enc = get_codec(codec)
            start = monotonic()
            for _ in range(N):
                try:
                    r = enc.encode(FORMAT, image)
                except Exception:
                    print("error on %s.%s" % (enc.get_type(), enc.encode))
                    raise
                if not r:
                    print("Error: no data")
                    break
            end = monotonic()
            print("%-10s   :    %.1f MPixels/s" % (enc.get_type(), w*h*N/(end-start)/1024/1024))
            cdata = r[1]
            #verify that the png data is valid using pillow:
            from io import BytesIO 
            buf = BytesIO(cdata.data)
            img = Image.open(buf)
            #img.show()

if __name__ == '__main__':
    main(sys.argv)
