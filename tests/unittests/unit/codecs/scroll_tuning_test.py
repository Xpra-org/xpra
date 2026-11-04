# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from importlib import import_module
from unittest.mock import patch

from xpra.codecs.checks import make_test_image
from xpra.util.objects import typedict


class ScrollTuningTest(unittest.TestCase):

    def codec(self, name):
        try:
            return import_module(f"xpra.codecs.{name}")
        except ImportError:
            self.skipTest(f"{name} is not available")

    def test_x264_switches_search_without_restarting(self):
        module = self.codec("x264.encoder")
        decoder_module = self.codec("openh264.decoder")
        self.enterContext(patch.object(module, "SCROLL_ME_RANGE", 64))
        self.enterContext(patch.object(module, "TUNE", "zerolatency"))
        for content_types in ((), ("text",), ("browser",), ("video",)):
            with self.subTest(content_types=content_types):
                encoder = module.Encoder()
                decoder = decoder_module.Decoder()
                image = make_test_image("YUV420P", 128, 128)
                options = typedict({"quality": 65, "speed": 80, "content-types": content_types, "b-frames": 0})
                try:
                    encoder.init_context("h264", 128, 128, "YUV420P", options)
                    decoder.init_context("h264", 128, 128, "YUV420P", typedict())
                    normal = encoder.get_info()["params"]["me"]
                    for frame_no, age in enumerate((None, 0, 999, 1000, -1, 0, None)):
                        frame_options = typedict(options)
                        if age is not None:
                            frame_options["scroll-age-ms"] = age
                        image.set_timestamp(frame_no + 1)
                        data, client_options = encoder.compress_image(image, frame_options)
                        self.assertTrue(data)
                        me = encoder.get_info()["params"]["me"]
                        if age is not None and 0 <= age < 1000:
                            self.assertEqual((me["type"], me["me-range"]), ("UMH", 64))
                        else:
                            self.assertEqual((me["type"], me["me-range"]), (normal["type"], normal["me-range"]))
                        if frame_no:
                            self.assertNotIn("type", client_options, "search changes must preserve P-frame prediction")
                        decoded = decoder.decompress_image(data, typedict(client_options))
                        self.assertIsNotNone(decoded)
                        decoded.free()
                    # A speed change during scrolling must also update the search restored afterwards.
                    options["speed"] = 100
                    control = module.Encoder()
                    try:
                        control.init_context("h264", 128, 128, "YUV420P", options)
                        expected = control.get_info()["params"]["me"]
                    finally:
                        control.clean()
                    for frame_no, age in ((8, 0), (9, None)):
                        frame_options = typedict(options)
                        if age is not None:
                            frame_options["scroll-age-ms"] = age
                        image.set_timestamp(frame_no + 1)
                        data, client_options = encoder.compress_image(image, frame_options)
                        decoded = decoder.decompress_image(data, typedict(client_options))
                        self.assertIsNotNone(decoded)
                        decoded.free()
                    me = encoder.get_info()["params"]["me"]
                    self.assertEqual((me["type"], me["me-range"]), (expected["type"], expected["me-range"]))
                finally:
                    image.free()
                    decoder.clean()
                    encoder.clean()

    def test_vpx_restores_cpu_used_and_preserves_requested_speed(self):
        module = self.codec("vpx.encoder")
        decoder_module = self.codec("vpx.decoder")
        self.enterContext(patch.object(module, "SCROLL_CPUUSED_DELTA", 2))
        for encoding in ("vp8", "vp9"):
            for speed in (20, 50, 80, 100):
                with self.subTest(encoding=encoding, speed=speed):
                    encoder = module.Encoder()
                    decoder = decoder_module.Decoder()
                    image = make_test_image("YUV420P", 128, 128)
                    options = typedict({"quality": 65, "speed": speed, "content-types": ("browser",)})
                    try:
                        encoder.init_context(encoding, 128, 128, "YUV420P", options)
                        decoder.init_context(encoding, 128, 128, "YUV420P", typedict())
                        normal = encoder.get_info()["cpu-used"]
                        for age in (None, 0, 999, 1000, -1, 0, None):
                            frame_options = typedict(options)
                            if age is not None:
                                frame_options["scroll-age-ms"] = age
                            data, client_options = encoder.compress_image(image, frame_options)
                            self.assertTrue(data)
                            info = encoder.get_info()
                            expected = normal
                            if encoding == "vp9" and age is not None and 0 <= age < 1000:
                                expected = min(normal, max(6, normal - 2))
                            self.assertEqual(info["cpu-used"], expected)
                            self.assertEqual(info["speed"], speed)
                            decoded = decoder.decompress_image(data, typedict(client_options))
                            self.assertIsNotNone(decoded)
                            decoded.free()
                    finally:
                        image.free()
                        decoder.clean()
                        encoder.clean()


if __name__ == "__main__":
    unittest.main()
