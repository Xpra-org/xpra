#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
import os
import sys
from PIL import Image

from xpra.util.objects import typedict
from xpra.util.str_fn import memoryview_to_bytes
from xpra.codecs.image import ImageWrapper
from xpra.codecs.loader import load_codec


def main(files):
    assert len(files) > 0, "specify images to test with"
    torch = load_codec("csc_torch")
    assert torch, "csc_torch is required"

    for index, f in enumerate(files):
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

        options = {}
        tfilter = torch.Filter()
        tfilter.init_context(w, h, pixel_format, w, h, "BGRX", typedict(options))
        output = tfilter.convert_image(source_image)
        bgrx = memoryview_to_bytes(output.get_pixels())
        img = Image.frombytes("RGBA", (w, h), bgrx, "raw", "RGBA", w*4, 1)
        path, ext = os.path.splitext(f)
        filename = f"{path}-torch{ext}"
        img.save(filename, "PNG")
        print(f"     saved to {filename!r}")


if __name__ == '__main__':
    assert len(sys.argv) > 1
    main(sys.argv[1:])
