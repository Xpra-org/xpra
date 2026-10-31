#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock, patch

from xpra.codecs.codec_constants import video_spec
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.codecs.loader import load_codec
from xpra.server.window import window_video_source
from xpra.server.window.window_video_source import WindowVideoSource
from xpra.util import typedict


class VideoEncodeTest(unittest.TestCase):

    def test_grayscale_conversion(self):
        if load_codec("csc_libyuv") is None:
            self.skipTest("libyuv converter is not available")

        pixels = bytes((0, 0, 255, 255, 0, 255, 0, 255, 255, 0, 0, 255, 50, 100, 200, 255))
        image = ImageWrapper(0, 0, 2, 2, pixels, "BGRX", 24, 8)
        self.addCleanup(image.free)
        source = WindowVideoSource.__new__(WindowVideoSource)
        source.pixel_format = "BGRX"
        source.supports_transparency = False
        source.encoding = "grayscale"
        source.image_depth = 24
        source.may_use_scrolling = Mock(return_value=False)
        source.video_helper = Mock()
        source.video_helper.get_encoder_specs.return_value = {}
        source.common_video_encodings = ("h264",)
        source.full_csc_modes = typedict()
        source.is_cancelled = Mock(return_value=False)
        source.check_pipeline = Mock(return_value=False)
        source.video_fallback = Mock(return_value=("fallback",))
        options = typedict()

        with patch.object(window_video_source, "videolog"):
            self.assertEqual(source.do_video_encode("grayscale", image, options), ("fallback",))

        converted = source.video_fallback.call_args.args[0]
        self.addCleanup(converted.free)
        source.video_fallback.assert_called_once_with(converted, options)
        source.check_pipeline.assert_called_once_with("grayscale", 2, 2, "BGRX")
        self.assertEqual(converted.get_geometry()[:4], image.get_geometry()[:4])
        self.assertEqual(converted.get_pixel_format(), "BGRX")
        gray_pixels = bytes(converted.get_pixels())
        self.assertEqual(len(gray_pixels), len(pixels))
        self.assertNotEqual(gray_pixels, pixels)
        for offset in range(0, len(gray_pixels), 4):
            b, g, r = gray_pixels[offset:offset + 3]
            self.assertEqual(b, g)
            self.assertEqual(g, r)


class VideoQualitySelectionTest(unittest.TestCase):

    def test_subsampling_inside_the_encoder_is_lossy(self):
        encoder = video_spec(
            encoding="h264", input_colorspace="BGRX", output_colorspaces=(), has_lossless_mode=False,
            codec_class=object, codec_type="test",
        )
        source = WindowVideoSource.__new__(WindowVideoSource)
        source.video_helper = Mock()
        source.video_helper.get_encoder_specs.return_value = {"BGRX": (encoder,)}
        source.video_helper.get_csc_specs.return_value = {}
        source._fixed_min_quality = 0
        source._current_speed = 50
        source._fixed_min_speed = 0
        source.video_max_size = (4096, 4096)
        source.video_subregion = None
        source.full_csc_modes = typedict({"h264": ("NV12", "YUV420P", "YUV422P", "YUV444P")})
        source.encoding_options = typedict()
        source._csc_encoder = None
        source._video_encoder = None
        source.matches_video_subregion = Mock(return_value=None)
        source.get_video_fps = Mock(return_value=0)
        source.is_cancelled = Mock(return_value=False)
        with patch.multiple(window_video_source, FORCE_CSC=False, PREFERRED_ENCODING_ORDER=("h264",)):
            for output_colorspaces, text, quality, shadow, penalty in (
                (("YUV420P",), True, 50, False, None),
                (("NV12",), True, 50, False, None),
                (("YUV422P",), True, 50, False, None),
                (("YUV420P",), False, 100, False, 0),
                (("YUV420P",), False, 50, True, -40),
                (("YUV420P", "YUV422P"), False, 50, True, -40),
                (("YUV420P",), False, 50, False, 0),
                (("YUV444P",), True, 100, True, 0),
                (("YUV420P", "YUV444P"), True, 100, True, 0),
            ):
                with self.subTest(output_colorspaces=output_colorspaces, text=text, quality=quality, shadow=shadow):
                    encoder.output_colorspaces = output_colorspaces
                    source.content_type = "text" if text else ""
                    source._current_quality = quality
                    source.is_shadow = shadow
                    with patch.object(window_video_source, "get_pipeline_score", return_value=(1,)) as scorer:
                        scores = source.get_video_pipeline_options(("h264",), 128, 128, "BGRX")
                    if penalty is None:
                        scorer.assert_not_called()
                        self.assertEqual(scores, ())
                    else:
                        scorer.assert_called_once()
                        self.assertEqual(scorer.call_args.args[12], penalty)
                        self.assertEqual(scores, ((1,),))


if __name__ == '__main__':
    unittest.main()
