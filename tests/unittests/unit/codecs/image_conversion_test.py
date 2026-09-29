#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from io import BytesIO


class ImageConversionTest(unittest.TestCase):

    def test_transparent_images_to_jpeg(self) -> None:
        from PIL import Image
        from xpra.clipboard.proxy import filter_data
        from xpra.codecs.image import to_rgb_image

        palette = Image.new("P", (16, 16), 0)
        palette.putpalette([255, 0, 0] + [0, 0, 0] * 255)
        palette.info["transparency"] = 0
        images = (
            ("RGBA", Image.new("RGBA", (16, 16), (255, 0, 0, 128)), (255, 127, 127)),
            ("LA", Image.new("LA", (16, 16), (40, 128)), (147, 147, 147)),
            ("palette", palette, (255, 255, 255)),
            ("grayscale", Image.new("L", (16, 16), 120), (120, 120, 120)),
        )
        for name, img, expected in images:
            with self.subTest(mode=name):
                rgb = to_rgb_image(img)
                self.assertEqual(rgb.mode, "RGB")
                self.assertEqual(rgb.getpixel((0, 0)), expected)
                buf = BytesIO()
                img.save(buf, "PNG")
                jpeg = filter_data("image/png", 8, buf.getvalue(), trusted=True, output_dtype="image/jpeg")
                with Image.open(BytesIO(jpeg)) as converted:
                    self.assertEqual(converted.mode, "RGB")
                    for actual, value in zip(converted.getpixel((8, 8)), expected):
                        self.assertAlmostEqual(actual, value, delta=4)


if __name__ == "__main__":
    unittest.main()
