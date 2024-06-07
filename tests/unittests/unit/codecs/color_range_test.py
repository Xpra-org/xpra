#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.objects import typedict
from xpra.codecs import loader
from xpra.codecs.checks import make_test_image, h2b


# pixel in RGBX order:
TEST_DATA = {
    "black": "000000ff",
    "white": "ffffffff",
    "green": "00ff00ff",
    "red": "ff0000ff",
    "blue": "0000ffff",
    "cyan": "00ffffff",
    "magenta": "ff00ffff",
    "yellow": "ffff00ff",
}


def convert_pixel(rgbx="00112233", fmt="BGRX") -> str:
    pixel = ""
    for color in fmt:
        index = "RGBX".index(color)         # "RGBX".index("R") -> 0
        pixel += rgbx[index*2:(index+1)*2]  # 0 -> "00"
    return pixel


class TestColorRange(unittest.TestCase):

    def test_save_rgb(self):
        width = 48
        height = 32
        for name in loader.ENCODER_CODECS:
            mod = loader.load_codec(name)
            if not mod:
                continue
            formats = mod.get_encodings()
            for fmt in formats:
                print(f"testing {fmt!r} from {mod}")
                for color, pixel in TEST_DATA.items():
                    rgb_format = "BGRX"
                    image = make_test_image(rgb_format, width, height)
                    size = image.get_rowstride() // 4 * image.get_height()
                    bgrx_pixel = convert_pixel(pixel, rgb_format)
                    pixels = h2b(bgrx_pixel) * size
                    image.set_pixels(pixels)
                    for quality, tolerance in {
                        "100": 1 if (name in ("enc_pillow", "enc_jpeg") and fmt in ("webp", "jpeg")) else 0,
                        "90": 3 if (name == "enc_pillow") else 2,
                        "50": 6,
                        "10": 16,
                    }.items():
                        options = typedict({"quality": quality})
                        bdata = mod.encode(fmt, image, options=options)
                        # tuple[str, Compressed, dict[str, Any], int, int, int, int]:
                        if bdata:
                            ext = fmt.replace("/", "")  # ie: "png/L" -> "pngL"
                            filename = f"./{name}-{color}.{ext}"
                            with open(filename, "wb") as f:
                                f.write(bdata[1].data)
                            if ext in ("png", "webp", "jpeg"):
                                from PIL import Image
                                img = Image.open(filename)
                                img = img.convert("RGBA")
                                rdata = img.tobytes("raw", rgb_format.replace("X", "A"))
                                # compare the first 4 pixels:
                                for i in range(16):
                                    ovalue = pixels[i]
                                    rvalue = rdata[i]
                                    if abs(ovalue - rvalue) > tolerance:
                                        raise RuntimeError(f"pixels reloaded from {filename} do not match:"
                                                           f"expected {pixels[:16]} but got {rdata[:16]}"
                                                           f"with {options=}")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
