#!/usr/bin/env python3

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.codecs.image import ImageWrapper
from xpra.codecs.loader import load_codec
from xpra.server.window.compress import WindowSource
from xpra.server.window.video_compress import WindowVideoSource
from xpra.util.objects import typedict


class VideoEncodeTest(unittest.TestCase):

    def test_grayscale_conversion(self) -> None:
        if load_codec("csc_libyuv") is None:
            self.skipTest("libyuv converter is not available")

        pixels = bytes((0, 0, 255, 255, 0, 255, 0, 255, 255, 0, 0, 255, 50, 100, 200, 255))
        image = ImageWrapper(0, 0, 2, 2, pixels, "BGRX", 24, 8)
        self.addCleanup(image.free)
        source = WindowVideoSource.__new__(WindowVideoSource)
        source.pixel_format = "BGRX"
        source.supports_transparency = False
        source.encoding = "grayscale"
        source.may_use_scrolling = Mock(return_value=False)
        source.video_helper = Mock()
        source.common_video_encodings = ("h264",)
        source.check_pipeline = Mock(return_value=False)
        source.video_fallback = Mock(return_value=("fallback",))
        options = typedict()

        self.assertEqual(source.do_video_encode("grayscale", image, options), ("fallback",))

        converted = source.video_fallback.call_args.args[0]
        self.addCleanup(converted.free)
        source.video_fallback.assert_called_once_with(converted, options, info="pipeline failed")
        source.check_pipeline.assert_called_once_with(("h264",), 2, 2, "BGRX")
        self.assertEqual(converted.get_geometry()[:4], image.get_geometry()[:4])
        self.assertEqual(converted.get_pixel_format(), "BGRX")
        gray_pixels = bytes(converted.get_pixels())
        self.assertEqual(len(gray_pixels), len(pixels))
        self.assertNotEqual(gray_pixels, pixels)
        for offset in range(0, len(gray_pixels), 4):
            b, g, r = gray_pixels[offset:offset + 3]
            self.assertEqual(b, g)
            self.assertEqual(g, r)


class NonVideoEncodingsTest(unittest.TestCase):

    def test_client_properties_exclude_unregistered_encodings(self):
        source = WindowVideoSource.__new__(WindowVideoSource)
        source.common_encodings = ("jpeg",)
        source.core_encodings = ("jpeg",)
        source.picture_encodings = ("jpeg", "webp")
        source._encoders = {"jpeg": Mock()}
        source.scroll_min_percent = 0
        source.scroll_preference = 100
        source.video_subregion = SimpleNamespace(supported=True)
        source.scaling_control = 0
        source.edge_encoding = ""
        source.full_csc_modes = typedict()

        def set_core_encodings(window_source, properties) -> None:
            window_source.core_encodings = properties.strtupleget("encodings.core", ())

        properties = typedict({"encodings.core": ("jpeg", "webp")})
        with patch.object(WindowSource, "do_set_client_properties", set_core_encodings):
            source.do_set_client_properties(properties)

        self.assertEqual(source.non_video_encodings, ("jpeg",))

    def test_missing_csc_modes_keeps_picture_encoders(self) -> None:
        source = WindowVideoSource.__new__(WindowVideoSource)
        source.wid = 1
        source.video_encodings = ("h264", "webp")
        source.core_encodings = ("h264", "webp", "rgb24")
        source._encoders = {"h264": source.video_encode, "webp": Mock(), "rgb24": Mock()}
        source.full_csc_modes = typedict()
        source.supports_transparency = True
        source._csc_encoder = source._video_encoder = None
        source.common_encodings = ()
        excluded = []

        def super_update(_window_source, _encoding, exclude, _init) -> None:
            excluded.extend(exclude)
        with patch.object(WindowSource, "update_encoding_selection", super_update):
            source.update_encoding_selection("webp")
        # no csc modes: neither one can go through the video pipeline,
        self.assertFalse(source.common_video_encodings)
        # but the picture encoder is still usable for "webp":
        self.assertEqual(excluded, ["h264"])


class ScalingCacheTest(unittest.TestCase):

    def test_candidate_limits_override_generic_scaling(self):
        source = WindowVideoSource.__new__(WindowVideoSource)
        source.video_helper = Mock()
        source.video_helper.get_csc_specs.return_value = {}
        encoder_spec = SimpleNamespace(
            can_scale=True,
            codec_type="test",
            max_w=2048,
            max_h=2048,
            output_colorspaces=("RGB",),
        )
        source.video_helper.get_encoder_specs.return_value = {"RGB": (encoder_spec,)}
        source._current_quality = source._current_speed = 50
        source._fixed_min_quality = source._fixed_min_speed = 0
        source.content_types = ()
        source.is_shadow = False
        source.video_max_size = (4096, 4096)
        source.video_subregion = None
        source.full_csc_modes = typedict({"h264": ("RGB",)})
        source.encoding_options = typedict()
        source._csc_encoder = source._video_encoder = None
        source.matches_video_subregion = Mock(return_value=None)
        source.get_video_fps = Mock(return_value=0)
        source.is_cancelled = Mock(return_value=False)
        source.calculate_scaling = Mock(side_effect=((1, 1), (2, 3)))

        with patch("xpra.server.window.video_compress.get_pipeline_score", return_value=(1,)) as score:
            source.get_video_pipeline_options(("h264",), 3000, 2000, "RGB")

        self.assertEqual(
            tuple(call.args for call in source.calculate_scaling.call_args_list),
            ((3000, 2000, 4096, 4096), (3000, 2000, 2048, 2048)),
        )
        self.assertEqual(score.call_args.args[5], (2, 3))


if __name__ == "__main__":
    unittest.main()
