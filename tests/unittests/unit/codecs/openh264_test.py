#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from importlib import import_module
from random import Random
from unittest.mock import patch

from xpra.codecs import openh264
from xpra.codecs.checks import make_test_image
from xpra.util.objects import typedict


class OpenH264QualityTest(unittest.TestCase):

    def setUp(self):
        self.enterContext(patch.multiple(openh264, MAX_QUALITY=45, LARGE_FRAME_MAX_QUALITY=35, LARGE_FRAME_PIXELS=1920 * 1080))

    def test_quality_caps_and_large_frame_boundary(self):
        for quality, width, height, expected in (
            (100, 128, 128, 45), (70, 1920, 1080, 45),
            (100, 1920, 1082, 35), (100, 3840, 2160, 35),
            (20, 3840, 2160, 20), (0, 128, 128, 0),
            (-1, 128, 128, 45), (-1, 3840, 2160, 35), (200, 128, 128, 45),
        ):
            with self.subTest(quality=quality, size=(width, height)):
                self.assertEqual(openh264.get_quality(quality, width, height), expected)

    def test_encoder_caps_initial_and_per_frame_quality(self):
        try:
            encoder_module = import_module("xpra.codecs.openh264.encoder")
        except ImportError:
            self.skipTest("OpenH264 encoder is not available")
        width = height = 128
        for profile in ("main", "constrained-baseline"):
            with self.subTest(profile=profile):
                encoder = encoder_module.Encoder()
                try:
                    encoder.init_context("h264", width, height, "YUV420P",
                                         typedict({"quality": 100, "h264.profile": profile}))
                    self.assertEqual(encoder.get_info()["quality"], 45)
                    image = make_test_image("YUV420P", width, height)
                    rng = Random(1)
                    image.set_pixels(tuple(rng.randbytes(len(plane)) for plane in image.get_pixels()))
                    for requested, expected in ((100, 45), (20, 20), (99, 45), (-1, 45)):
                        data, client_options = encoder.compress_image(image, typedict({"quality": requested}))
                        self.assertTrue(data)
                        self.assertEqual(encoder.get_info()["quality"], expected)
                        self.assertEqual(client_options["quality"], expected)
                finally:
                    encoder.clean()

    def test_4k_noise_at_requested_quality_100_roundtrips(self):
        try:
            encoder_module = import_module("xpra.codecs.openh264.encoder")
            decoder_module = import_module("xpra.codecs.openh264.decoder")
        except ImportError:
            self.skipTest("OpenH264 encoder and decoder are not available")
        width, height = 3840, 2160
        image = make_test_image("YUV420P", width, height)
        rng = Random(1)
        image.set_pixels(tuple(rng.randbytes(len(plane)) for plane in image.get_pixels()))
        for profile in ("main", "constrained-baseline"):
            for speed in (50, 80):
                with self.subTest(profile=profile, speed=speed):
                    encoder = encoder_module.Encoder()
                    decoder = decoder_module.Decoder()
                    try:
                        options = typedict({"quality": 100, "speed": speed, "h264.profile": profile})
                        encoder.init_context("h264", width, height, "YUV420P", options)
                        self.assertEqual(encoder.get_info()["quality"], 35)
                        data, client_options = encoder.compress_image(image, options)
                        self.assertEqual(client_options["quality"], 35)
                        # Stock OpenH264 decoders reject access units above this size.
                        self.assertLessEqual(len(data), 7_077_888)
                        decoder.init_context("h264", width, height, "YUV420P", typedict())
                        decoded = decoder.decompress_image(data, typedict(client_options))
                        self.assertIsNotNone(decoded)
                        self.assertEqual((decoded.get_width(), decoded.get_height()), (width, height))
                        decoded.free()
                    finally:
                        encoder.clean()
                        decoder.clean()


if __name__ == "__main__":
    unittest.main()
