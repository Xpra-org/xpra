#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from io import BytesIO
from time import monotonic
from PIL import Image

from xpra.net import compression
from xpra.util.env import envbool
from xpra.codecs.image import ImageWrapper
from xpra.codecs.loader import load_codec

N = 10
CODECS = ("enc_rgb", "enc_pillow", "enc_spng", "enc_webp", "enc_jpeg", "enc_avif")
#CODECS = ("enc_rgb", "enc_pillow", "enc_spng", "enc_webp", "enc_jpeg", "enc_nvjpeg", "enc_avif")

options = {
    #"quality" : 10,
    #"grayscale" : True,
}


def main(fmt="png", files=()):
    assert len(files)>0, "specify images to use for benchmark"
    compression.init_all()
    encoders = []
    for codec in CODECS:
        enc = load_codec(codec)
        if enc and (fmt=="all" or fmt in enc.get_encodings()):
            encoders.append(enc)
    index = 0
    for f in files:
        index += 1
        img = Image.open(f)
        if img.mode not in ("RGBA", "RGB"):
            img = img.convert("RGB")
        pixel_format = img.mode
        w, h = img.size
        rgb_data = img.tobytes("raw")
        stride = w * len(pixel_format)
        print(f"{f:40} : {img}")
        image = ImageWrapper(0, 0, w, h,
                             rgb_data, pixel_format, len(pixel_format)*8, stride,
                             planes=ImageWrapper.PACKED, thread_safe=True)
        for enc in encoders:
            if fmt=="all":
                encodings = enc.get_encodings()
            else:
                encodings = (fmt,)
            for encoding in encodings:
                size = 0
                start = monotonic()
                for _ in range(N):
                    try:
                        r = enc.encode(encoding, image, options)
                    except Exception:
                        print(f"error on {enc.get_type()} : {enc.encode}")
                        raise
                    if not r:
                        print(f"Error: no data for {enc.get_type()} : {enc.encode}")
                        break
                    size += len(r[1])
                if not r:
                    continue
                end = monotonic()
                cdata = r[1]
                if envbool("SAVE", False):
                    filename = f"./benchmark-{index}-{enc.get_type()}.{encoding.replace('/','-')}"
                    bdata = getattr(cdata, "data", cdata)
                    with open(filename, "wb") as fsave:
                        fsave.write(bdata)
                ratio = 100*len(cdata)/len(rgb_data)
                mps = w*h*N/(end-start)/1024/1024
                sizek = size*N//1024
                print(f"{encoding:10} {enc.get_type():10} {mps:10.1f} MPixels/s  {sizek:>8}KB  {ratio:3.1f}%")
                #verify that the png data is valid using pillow:
                if encoding not in ("rgb24", "rgb32", "avif"):
                    buf = BytesIO(cdata.data)
                    img = Image.open(buf)
                    #img.show()


if __name__ == '__main__':
    assert len(sys.argv)>1
    files = sys.argv[1:]
    fmt = "png"
    if files[0] in ("png", "webp", "jpeg", "rgb24", "rgb32", "all", "avif"):
        fmt = files[0]
        files = files[1:]
    main(fmt, files)
