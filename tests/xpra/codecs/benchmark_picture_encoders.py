#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from time import monotonic

from xpra.codecs.image_wrapper import ImageWrapper

N = 10
CODECS = ("enc_rgb", "enc_pillow", "enc_spng", "enc_webp", "enc_jpeg", "enc_nvjpeg")

#options = {"grayscale" : True}
options = {}


def main(fmt="png", files=()):
    assert len(files)>0, "specify images to benchmark"
    from xpra.net import compression
    compression.init_all()
    from xpra.codecs.loader import load_codec, get_codec
    encoders = []
    for codec in CODECS:
        load_codec(codec)
        enc = get_codec(codec)
        if enc and fmt in enc.get_encodings():
            encoders.append(enc)

    from PIL import Image
    for f in files:
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
        for enc in encoders:
            size = 0
            start = monotonic()
            for _ in range(N):
                try:
                    r = enc.encode(fmt, image, options)
                except Exception:
                    print("error on %s %s" % (enc.get_type(), enc.encode))
                    raise
                if not r:
                    print("Error: no data for %s %s" % (enc.get_type(), enc.encode))
                    break
                size += len(r[1])
            if not r:
                continue
            end = monotonic()
            print("%-10s   :    %.1f MPixels/s    size=%iKB" % (
                enc.get_type(), w*h*N/(end-start)/1024/1024, size*N/1024))
            cdata = r[1]
            #verify that the png data is valid using pillow:
            from io import BytesIO 
            buf = BytesIO(cdata.data)
            img = Image.open(buf)
            #img.show()

if __name__ == '__main__':
    assert len(sys.argv)>1
    files = sys.argv[1:]
    fmt = "png"
    if files[0] in ("png", "webp", "jpeg", "rgb24", "rgb32"):
        fmt = files[0]
        files = files[1:]
    main(fmt, files)
