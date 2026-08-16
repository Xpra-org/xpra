#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.codecs import loader
from xpra.codecs.checks import make_test_image
from xpra.util.objects import typedict


class H264ProfileTest(unittest.TestCase):

    def test_openh264_decoder_non_delayed_profiles(self):
        decoder_module = loader.load_codec("dec_openh264")
        if not decoder_module:
            self.skipTest("OpenH264 decoder is not available")
        width = height = 128
        tested = []
        for codec_name in ("enc_x264", "enc_openh264"):
            encoder_module = loader.load_codec(codec_name)
            if not encoder_module:
                continue
            for profile in ("main", "high"):
                with self.subTest(encoder=codec_name, profile=profile):
                    encoder = encoder_module.Encoder()
                    decoder = decoder_module.Decoder()
                    try:
                        options = typedict({
                            "h264.profile": profile,
                            "dst-formats": ("YUV420P", ),
                            "quality": 90,
                            "b-frames": 0,
                        })
                        encoder.init_context("h264", width, height, "YUV420P", options)
                        decoder.init_context("h264", width, height, "YUV420P", typedict())
                        for luma in (0x40, 0x80, 0xc0):
                            image = make_test_image("YUV420P", width, height, (luma, 0x80, 0x80))
                            data, client_options = encoder.compress_image(image, typedict())
                            self.assertNotIn("delayed", client_options)
                            decoded = decoder.decompress_image(data, typedict(client_options))
                            self.assertIsNotNone(decoded)
                            self.assertAlmostEqual(decoded.get_pixels()[0][0], luma, delta=2)
                            decoded.free()
                    finally:
                        encoder.clean()
                        decoder.clean()
            tested.append(codec_name)
        if not tested:
            self.skipTest("no H.264 software encoder available")


if __name__ == "__main__":
    unittest.main()
