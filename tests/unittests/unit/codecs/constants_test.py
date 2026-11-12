#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gc
import os
import unittest
from unittest.mock import patch

from xpra.codecs.constants import (
    CodecSpec,
    VideoSpec,
    get_profile,
    get_subsampling_divs,
    get_x264_preset,
    get_x264_quality,
)
from xpra.util.objects import typedict


class Codec:
    pass


class CodecConstantsTest(unittest.TestCase):

    def test_video_spec_preserves_requested_quality(self):
        spec = VideoSpec(codec_class=Codec, codec_type="test")
        for quality in (-1, 0, 50, 100):
            for width, height in ((128, 128), (3840, 2160)):
                with self.subTest(quality=quality, size=(width, height)):
                    self.assertEqual(spec.get_effective_quality(quality, width, height), quality)

    def test_pixel_format_and_x264_boundaries(self):
        self.assertEqual(get_subsampling_divs("YUV420P10"), ((1, 1), (2, 2), (2, 2)))
        with self.assertRaises(ValueError):
            get_subsampling_divs("invalid")
        self.assertEqual(get_x264_quality(100, "high444"), 0)
        self.assertEqual(get_x264_quality(-1), 50)
        self.assertEqual(get_x264_preset(100), 0)
        self.assertGreater(get_x264_preset(0), get_x264_preset(99))

    def test_profile_precedence(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(get_profile(typedict()), "main")
            self.assertEqual(get_profile(typedict({"h264.profile": "general"})), "general")
            options = typedict({"h264.YUV420P.profile": "specific", "h264.profile": "general"})
            self.assertEqual(get_profile(options), "specific")
        environment = {
            "XPRA_H264_PROFILE": "environment-general",
            "XPRA_H264_YUV420P_PROFILE": "environment-specific",
        }
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(get_profile(typedict()), "environment-specific")
            self.assertEqual(get_profile(typedict({"h264.profile": "option"})), "option")

    def test_codec_spec_lifecycle_and_serialization(self):
        spec = CodecSpec(codec_class=Codec, codec_type="test", max_instances=2)
        self.assertEqual(spec.get_runtime_factor(), 1.0)
        instance = spec.make_instance()
        self.assertEqual(spec.get_instance_count(), 1)
        self.assertEqual(spec.get_runtime_factor(), 0.75)
        data = spec.to_dict("codec_class")
        self.assertNotIn("instances", data)
        self.assertNotIn("codec_class", data)
        second = spec.make_instance()
        self.assertEqual(spec.get_runtime_factor(), 0)
        del instance, second
        gc.collect()
        self.assertEqual(spec.get_instance_count(), 0)


class BufferChecksTest(unittest.TestCase):

    def test_rgb_buffer(self):
        from xpra.codecs.constants import check_rgb_buffer
        check_rgb_buffer("BGRX", 400, 10, 10, 40)
        # the last row needs no padding:
        check_rgb_buffer("RGB", 48 * 9 + 30, 10, 10, 48)
        for args in (
            ("BGRX", 399, 10, 10, 40),
            ("BGRX", 400, 10, 10, 39),
            ("BGRX", 10**9, 10, 10, 10**8),
            ("BGRX", 400, 0, 10, 40),
            ("FOO", 400, 10, 10, 40),
        ):
            with self.assertRaises(ValueError, msg=f"{args} accepted"):
                check_rgb_buffer(*args)

    def test_image_planes(self):
        from xpra.codecs.image import ImageWrapper
        from xpra.codecs.constants import check_image_planes

        def image(pixel_format, pixels, strides, planes, w=10, h=10):
            return ImageWrapper(0, 0, w, h, pixels, pixel_format, 24, strides, 1, planes)

        check_image_planes(image("BGRX", (bytes(400), ), 40, 0), 10, 10, ("BGRX", "RGBX"))
        check_image_planes(image("NV12", (bytes(100), bytes(50)), (10, 10), 2), 10, 10)
        check_image_planes(image("YUV420P10", (bytes(200), bytes(50), bytes(50)), (20, 10, 10), 3), 10, 10)
        # odd dimensions round up the subsampled planes:
        check_image_planes(image("YUV420P", (bytes(99), bytes(30), bytes(30)), (11, 6, 6), 3, 11, 9), 11, 9)
        # GPU images without CPU pixels, and formats we don't know the layout of:
        check_image_planes(image("NV12", (), (10, 10), 2), 10, 10)
        check_image_planes(image("Y410", (b"", ), 40, 0), 10, 10)
        for img, formats in (
            (image("BGRX", (bytes(400), ), 40, 0, 10, 9), ()),
            (image("BGRX", (bytes(400), ), 40, 0), ("RGB", )),
            (image("BGRX", (bytes(400), ), (40, ), 0), ()),
            (image("BGRX", (bytes(400), ), 40, 3), ()),
            (image("NV12", (bytes(100), bytes(49)), (10, 10), 2), ()),
            (image("NV12", (bytes(100), ), (10, ), 2), ()),
            (image("YUV420P10", (bytes(100), bytes(25), bytes(25)), (10, 5, 5), 3), ()),
            (image("YUV420P", (bytes(100), bytes(25)), (10, 5, 5), 3), ()),
        ):
            with self.assertRaises(ValueError, msg=f"{img} accepted"):
                check_image_planes(img, 10, 10, formats)


if __name__ == "__main__":
    unittest.main()
