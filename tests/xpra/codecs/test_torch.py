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

    transforms = (
        #"RandomInvert(p=0.5)",
        #"Grayscale",
        "ColorJitter(brightness=.5, hue=.3)",
        "GaussianNoise(mean=0.0, sigma=0.1, clip=True)",
        #"GaussianBlur(kernel_size=(5, 9), sigma=(0.1, 5.))",
        "functional.vflip",
        "functional.hflip",
        #"functional.gaussian_blur",
        "functional.invert",
        "functional.posterize(bits=4)",
        "functional.solarize(threshold=0.5)",
        #adjust_sharpness
        "functional.autocontrast",
        "functional.equalize",
    )

    for index, f in enumerate(files):
        img = Image.open(f)
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        pixel_format = "BGRX"
        w, h = img.size
        stride = w * len(pixel_format)
        print(f"{index} : {f:40} : {img}")

        for i, transform in enumerate(transforms):
            rgb_data = img.tobytes("raw")
            source_image = ImageWrapper(0, 0, w, h,
                                        rgb_data, pixel_format, len(pixel_format) * 8, stride,
                                        planes=ImageWrapper.PACKED, thread_safe=True)

            transform_name = transform.split("(", 1)[0]
            if transform_name.startswith("functional."):
                transform_name = transform_name.split(".", 1)[1]
            print(f" - {transform_name}")

            options = {"transform": transform}
            tfilter = torch.Filter()
            tfilter.init_context(w, h, pixel_format, w, h, "BGRX", typedict(options))
            output = tfilter.convert_image(source_image)
            bgrx = memoryview_to_bytes(output.get_pixels())
            # print("bgrx=%s (%i bytes)" % (repr_ellipsized(bgrx), len(bgrx)))
            result = Image.frombytes("RGBA", (w, h), bgrx, "raw", "RGBA", w*4, 1)
            path, ext = os.path.splitext(f)
            filename = f"{path}-{i}-{transform_name}{ext}"
            result.save(filename, "PNG")
            print(f"     saved to {filename!r}")


if __name__ == '__main__':
    assert len(sys.argv) > 1
    main(sys.argv[1:])
