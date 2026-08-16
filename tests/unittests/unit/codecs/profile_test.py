#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.codecs import loader
from xpra.codecs.checks import make_test_image
from xpra.util.objects import typedict


def get_sps_profile(data: bytes) -> int:
    """Return profile_idc from the first Annex-B SPS."""
    pos = 0
    while pos < len(data) - 5:
        if data[pos:pos + 4] == b"\0\0\0\1":
            nal = pos + 4
        elif data[pos:pos + 3] == b"\0\0\1":
            nal = pos + 3
        else:
            pos += 1
            continue
        if data[nal] & 0x1f == 7:
            return data[nal + 1]
        pos = nal + 1
    raise ValueError("H.264 stream has no SPS")


def canonical_profile(profile: str) -> str:
    return "constrained-baseline" if profile == "baseline" else profile


class H264ProfileTest(unittest.TestCase):

    def test_software_encoder_profiles(self):
        width = height = 128
        tested = []
        for codec_name in ("enc_x264", "enc_openh264"):
            encoder_module = loader.load_codec(codec_name)
            if not encoder_module:
                continue
            for requested, expected_profile, expected_idc in (
                    ("", "main", 77),
                    ("baseline", "constrained-baseline", 66),
                    ("constrained-baseline", "constrained-baseline", 66),
                    ("main", "main", 77),
                    ("high", "high", 100),
            ):
                encoder = encoder_module.Encoder()
                options = typedict({
                    "dst-formats": ("YUV420P", ),
                    "quality": 50,
                    "speed": 50,
                })
                if requested:
                    options["h264.profile"] = requested
                try:
                    encoder.init_context("h264", width, height, "YUV420P", options)
                    image = make_test_image("YUV420P", width, height)
                    data, client_options = encoder.compress_image(image, typedict())
                    self.assertEqual(get_sps_profile(data), expected_idc, (codec_name, requested))
                    self.assertEqual(canonical_profile(client_options.get("profile", "")), expected_profile)
                    self.assertEqual(canonical_profile(encoder.get_info().get("profile", "")), expected_profile)
                finally:
                    encoder.clean()
            tested.append(codec_name)
        if not tested:
            self.skipTest("no H.264 software encoder available")

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
