#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from io import BytesIO
from unittest.mock import patch

from PIL import Image

from xpra.codecs.pillow import decoder
from xpra.util.objects import typedict


def png_data(mode: str, pixel: tuple[int, ...]) -> bytes:
    image = Image.new(mode, (1, 1), pixel)
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


class PillowDecoderTest(unittest.TestCase):

    def test_requested_bgra(self) -> None:
        data = png_data("RGBA", (100, 50, 25, 128))
        rgb_format, pixels, width, height, rowstride = decoder.decompress(
            "png", data, typedict({"rgb_format": "BGRA"}),
        )
        self.assertEqual(rgb_format, "BGRA")
        self.assertEqual(bytes(pixels), bytes((25, 50, 100, 128)))
        self.assertEqual((width, height, rowstride), (1, 1, 4))

    def test_requested_bgrx(self) -> None:
        data = png_data("RGBA", (100, 50, 25, 128))
        rgb_format, pixels, width, height, rowstride = decoder.decompress(
            "png", data, typedict({"rgb_format": "BGRX"}),
        )
        self.assertEqual(rgb_format, "BGRX")
        self.assertEqual(bytes(pixels[:3]), bytes((25, 50, 100)))
        self.assertEqual((width, height, rowstride), (1, 1, 4))

    def test_add_alpha_for_requested_bgra(self) -> None:
        data = png_data("RGB", (100, 50, 25))
        rgb_format, pixels, width, height, rowstride = decoder.decompress(
            "png", data, typedict({"rgb_format": "BGRA"}),
        )
        self.assertEqual(rgb_format, "BGRA")
        self.assertEqual(bytes(pixels), bytes((25, 50, 100, 255)))
        self.assertEqual((width, height, rowstride), (1, 1, 4))

    def test_unsupported_requested_format(self) -> None:
        data = png_data("RGBA", (100, 50, 25, 128))
        with patch.object(decoder, "log") as log:
            rgb_format, pixels, width, height, rowstride = decoder.decompress(
                "png", data, typedict({"rgb_format": "ARGB"}),
            )
        log.warn.assert_called_once()
        self.assertEqual(rgb_format, "RGBA")
        self.assertEqual(bytes(pixels), bytes((100, 50, 25, 128)))
        self.assertEqual((width, height, rowstride), (1, 1, 4))

    @unittest.skipUnless("webp" in decoder.get_encodings(), "Pillow WebP support is unavailable")
    def test_requested_webp_bgra(self) -> None:
        image = Image.new("RGBA", (1, 1), (100, 50, 25, 128))
        buffer = BytesIO()
        image.save(buffer, "WEBP", lossless=True)
        rgb_format, pixels, width, height, rowstride = decoder.decompress(
            "webp", buffer.getvalue(), typedict({"rgb_format": "BGRA"}),
        )
        self.assertEqual(rgb_format, "BGRA")
        self.assertEqual(bytes(pixels), bytes((25, 50, 100, 128)))
        self.assertEqual((width, height, rowstride), (1, 1, 4))


if __name__ == "__main__":
    unittest.main()
