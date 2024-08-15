#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct
import cairo
import unittest
from time import monotonic
from io import BytesIO
from PIL import Image

from xpra.codecs.checks import TEST_COLORS
from xpra.gtk.cairo_image import make_image_surface


N = 5
WIDTH, HEIGHT = 256, 256


def surface_to_pil(img) -> Image:
    save = BytesIO()
    img.write_to_png(save)
    pixels = save.getvalue()
    save.close()
    return Image.open(BytesIO(pixels))


class CairoColorsTest(unittest.TestCase):

    def test_compare(self):
        for color_name, hex_pixel in TEST_COLORS.items():
            # color components as integers:
            r, g, b, a = (int(hex_pixel[i * 2:(i + 1) * 2], 16) for i in range(4))
            # color components as bytes:
            rb, gb, bb, ab = (struct.pack("B", pixel_int) for pixel_int in (r, g, b, a))
            # map component to byte values:
            pix_vals: dict[str, bytes] = {
                "R": rb,
                "G": gb,
                "B": bb,
                "A": ab,
                "X": ab,
            }
            for format_name, cairo_format in {
                "ARGB32": cairo.Format.ARGB32,
                "RGB24": cairo.Format.RGB24,
            }.items():
                # try with our code:
                for rgb_format in ("RGBA", "RGBX", "BGRA", "BGRX", "RGB", "BGR"):
                    stride = WIDTH * len(rgb_format)
                    pixels = (b"".join(pix_vals[component] for component in rgb_format)) * stride * HEIGHT
                    start = monotonic()
                    for _ in range(N):
                        img = make_image_surface(cairo_format, rgb_format, pixels, WIDTH, HEIGHT, stride)
                    end = monotonic()
                    if color_name == "blue":
                        mps = round(N*WIDTH*HEIGHT / (end-start) / 1024 / 1024)
                        print(f"{rgb_format:<4} to cairo.{format_name: <6} : {mps:>5} MPixels/s")
                    pimg = surface_to_pil(img)
                    pixel = pimg.getpixel((WIDTH//2, HEIGHT//2))
                    if pixel != (r, g, b):
                        raise ValueError(f"expected {(r, g, b)} but got {pixel}")

                # try painting the same color using cairo
                img = cairo.ImageSurface(cairo_format, WIDTH, HEIGHT)
                ctx = cairo.Context(img)
                ctx.set_source_rgb(r/255, g/255, b/255)
                ctx.rectangle(0, 0, WIDTH, HEIGHT)
                ctx.fill()
                # img.write_to_png(f"{color_name}-cairo.png")
                pimg = surface_to_pil(img)
                pixel = pimg.getpixel((WIDTH//2, HEIGHT//2))
                if pixel != (r, g, b):
                    raise ValueError(f"expected {(r, g, b)} but got {pixel}")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
