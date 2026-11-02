#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from importlib import import_module

from xpra.codecs.checks import make_test_image
from xpra.util.objects import typedict


class WebPEncoderTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        try:
            cls.encoder_module = import_module("xpra.codecs.webp.encoder")
            cls.decoder_module = import_module("xpra.codecs.webp.decoder")
        except ImportError:
            raise unittest.SkipTest("WebP encoder and decoder are not available") from None

    def check_resize(self, stateful):
        width, height = 128, 96
        for pixel_format in ("BGRX", "BGRA"):
            for quality in (50, 100):
                image = make_test_image(pixel_format, width, height)
                encoder = self.encoder_module.Encoder() if stateful else None
                if encoder:
                    encoder.init_context("webp", width, height, pixel_format, typedict({"quality": quality}))
                    self.addCleanup(encoder.clean)
                for requested, expected in (
                    ((64, 48), (64, 48)),
                    ((64, 96), (64, 96)),
                    ((0, 48), (64, 48)),
                    (None, (width, height)),
                ):
                    with self.subTest(pixel_format=pixel_format, quality=quality, requested=requested):
                        options = typedict({"quality": quality})
                        if requested:
                            options.update(zip(("scaled-width", "scaled-height"), requested))
                        if encoder:
                            data, client_options = encoder.compress_image(image, options)
                        else:
                            coding, data, client_options, outw, outh, _stride, _bpp = self.encoder_module.encode("webp", image, options)
                            self.assertEqual(coding, "webp")
                            # Draw dimensions cover the original destination region.
                            self.assertEqual((outw, outh), (width, height))
                            data = data.data
                        decoded = self.decoder_module.decompress_to_rgb(data, typedict(client_options))
                        try:
                            self.assertEqual((decoded.get_width(), decoded.get_height()), expected)
                        finally:
                            decoded.free()
                        if expected == (width, height):
                            self.assertNotIn("scaled_size", client_options)
                        else:
                            self.assertEqual(client_options.get("scaled_size"), expected)

    def test_encode_resize(self):
        self.check_resize(False)

    def test_compress_image_resize(self):
        self.check_resize(True)


if __name__ == "__main__":
    unittest.main()
