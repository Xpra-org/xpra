#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import cairo
import unittest
from io import BytesIO
from PIL import Image

from xpra.codecs.checks import TEST_COLORS, h2b
from xpra.client.gtk3.cairo_workaround import make_image_surface


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
            r, g, b = (int(hex_pixel[i * 2:(i + 1) * 2], 16) for i in range(3))
            # try with our code:
            pixels = h2b(hex_pixel) * WIDTH * HEIGHT
            img = make_image_surface(cairo.FORMAT_ARGB32, "RGBA", pixels, WIDTH, HEIGHT, WIDTH*4)
            pimg = surface_to_pil(img)
            pixel = pimg.getpixel((WIDTH//2, HEIGHT//2))
            if pixel != (r, g, b):
                raise ValueError(f"expected {(r, g, b)} but got {pixel}")

            # try painting the color using cairo
            img = cairo.ImageSurface(cairo.Format.ARGB32, WIDTH, HEIGHT)
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
