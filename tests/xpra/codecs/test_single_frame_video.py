#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
from PIL import Image

from xpra.util.objects import typedict
from xpra.util.env import envbool
from xpra.util.str_fn import memoryview_to_bytes
from xpra.codecs.image import ImageWrapper
from xpra.codecs.loader import load_codec


def main(files):
    assert len(files) > 0, "specify images to use for benchmark"
    avcodec = load_codec("dec_avcodec2")
    assert avcodec, "dec_avcodec is required"
    encoders = []
    ENCODERS = os.environ.get("XPRA_ENCODERS", "enc_vpx,enc_x264,nvenc").split(",")
    for encoder in ENCODERS:
        enc = load_codec(encoder)
        if not enc:
            print(f"{encoder} not found")
            continue
        print(f"* {encoder}")
        encodings = enc.get_encodings()
        for encoding in encodings:
            print(f"  - {encoding}")
            if encoding not in avcodec.get_encodings():
                print(f"    {avcodec} cannot decode {encoding}")
                continue
            matches = []
            for ics in enc.get_input_colorspaces(encoding):
                if ics not in ("BGRX", "YUV420P", "YUV444P",):
                    print(f"    skipping {ics}")
                    continue
                dcs = avcodec.get_output_colorspaces(encoding, ics)
                print(f"    dec_avcodec output colorspace for {encoding} + {ics} : {dcs}")
                if any(x in dcs for x in ("BGRX", "BGR", "YUV420P", "YUV444P", "GBRP")):
                    encoders.append((encoding, ics, enc))
                    matches.append(ics)
            if not matches:
                print(f"     no BGRX match for {encoding}")
    index = 0
    for f in files:
        index += 1
        img = Image.open(f)
        print(f"{index} : {f:40} : {img}")
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        pixel_format = "BGRX"
        w, h = img.size
        rgb_data = img.tobytes("raw")
        stride = w * len(pixel_format)
        source_image = ImageWrapper(0, 0, w, h,
                                    rgb_data, pixel_format, len(pixel_format) * 8, stride,
                                    planes=ImageWrapper.PACKED, thread_safe=True)
        #source_image.restride(roundup(w*4, 8))
        for encoding, colorspace, enc in encoders:
            print(f"  {enc.get_type():10} {encoding:10} {colorspace}")
            image = source_image
            if colorspace != "BGRX":
                from xpra.codecs.libyuv.converter import Converter
                csc = Converter()
                csc.init_context(w, h, pixel_format,
                                 w, h, colorspace, typedict({"speed": 0}))
                image = csc.convert_image(source_image)
            encoder = enc.Encoder()
            try:
                encoder.init_context(encoding, w, h, image.get_pixel_format(), typedict({"quality": 100, "speed": 0}))
            except ValueError:
                print(f"  encoder rejected {w}x{h} {image.get_pixel_format()}")
                continue
            try:
                td = typedict()
                r = encoder.compress_image(image, td)
            except Exception:
                print(f"error on {enc.get_type()} : {enc.encode}")
                raise
            if not r:
                print(f"Error: no data for {enc.get_type()} : {enc.encode}")
                continue
            cdata, client_options = r
            print(f"r={r}")
            bdata = getattr(cdata, "data", cdata)
            if envbool("SAVE", False):
                filename = f"./{index}-{enc.get_type()}.{encoding.replace('/', '-')}"
                with open(filename, "wb") as fsave:
                    fsave.write(bdata)
            #now decode it back into an RGB picture:
            decoder = avcodec.Decoder()
            decoder.init_context(encoding, w, h, colorspace)
            decoded = decoder.decompress_image(bdata, typedict(client_options))
            dformat = decoded.get_pixel_format()
            output = decoded
            if dformat != "BGRX":
                from xpra.codecs.libyuv.converter import Converter
                csc = Converter()
                csc.init_context(w, h, dformat, w, h, "BGRX", typedict())
                output = csc.convert_image(decoded)
                print(f"    converted {dformat} to BGRX")
            obytes = memoryview_to_bytes(output.get_pixels())
            output_image = Image.frombuffer("RGBA", (w, h), obytes, "raw", "BGRA", output.get_rowstride())
            filename = f"{index}-{enc.get_type()}-{encoding}-{colorspace}.png"
            output_image.save(filename, "PNG")
            print(f"     saved to {filename!r}")


if __name__ == '__main__':
    assert len(sys.argv) > 1
    main(sys.argv[1:])
