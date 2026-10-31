# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.codecs.image import ImageWrapper
from xpra.codecs.loader import load_codec
from xpra.server.window.compress import WindowSource
from xpra.server.window.video_compress import WindowVideoSource
from xpra.util.objects import typedict


class VideoContextCleanTest(unittest.TestCase):

    @staticmethod
    def make_source(csc=None, encoder=None) -> WindowVideoSource:
        source = WindowVideoSource.__new__(WindowVideoSource)
        source._csc_encoder = csc
        source._video_encoder = encoder
        source.cancel_video_encoder_flush = Mock()
        source.cancel_video_encoder_timer = Mock()
        source.call_in_encode_thread = Mock()
        source.csc_clean = Mock()
        source.ve_clean = Mock()
        source.wid = 1
        return source

    def test_cancels_timers_without_a_context(self) -> None:
        source = self.make_source()

        source.video_context_clean()

        source.cancel_video_encoder_flush.assert_called_once_with()
        source.cancel_video_encoder_timer.assert_called_once_with()
        source.call_in_encode_thread.assert_called_once()
        clean, = source.call_in_encode_thread.call_args.args

        clean()

        self.assertEqual(source.cancel_video_encoder_flush.call_count, 2)
        self.assertEqual(source.cancel_video_encoder_timer.call_count, 2)
        source.csc_clean.assert_not_called()
        source.ve_clean.assert_not_called()

    def test_cleans_context_published_after_empty_snapshot(self) -> None:
        source = self.make_source()

        source.video_context_clean()
        clean, = source.call_in_encode_thread.call_args.args

        csc = Mock()
        encoder = Mock()
        source._csc_encoder = csc
        source._video_encoder = encoder
        clean()

        self.assertIsNone(source._csc_encoder)
        self.assertIsNone(source._video_encoder)
        source.csc_clean.assert_called_once_with(csc)
        source.ve_clean.assert_called_once_with(encoder)

    def test_detaches_and_cleans_context(self) -> None:
        csc = Mock()
        encoder = Mock()
        source = self.make_source(csc, encoder)

        source.video_context_clean()

        self.assertIsNone(source._csc_encoder)
        self.assertIsNone(source._video_encoder)
        source.call_in_encode_thread.assert_called_once()
        clean, = source.call_in_encode_thread.call_args.args

        clean()

        self.assertEqual(source.cancel_video_encoder_flush.call_count, 2)
        source.csc_clean.assert_called_once_with(csc)
        source.ve_clean.assert_called_once_with(encoder)

    def test_ve_clean_still_cancels_its_timer(self) -> None:
        encoder = Mock()
        source = self.make_source()

        WindowVideoSource.ve_clean(source, encoder)

        source.cancel_video_encoder_timer.assert_called_once_with()
        encoder.clean.assert_called_once_with()

    def test_closed_encoder_flush_saves_data_before_cleanup(self) -> None:
        source = self.make_source()
        encoder = Mock()
        encoder.is_closed.side_effect = (False, True)
        encoder.get_type.return_value = "test"
        encoder.get_width.return_value = 64
        encoder.get_height.return_value = 64
        encoder.get_encoding.return_value = "h264"
        encoder.flush.return_value = b"data", {}
        source._video_encoder = encoder
        source.b_frame_flush_data = encoder, None, 1, 0, 0, None, False
        source.b_frame_flush_timer = 0
        source.start_video_frame = 0
        events = []
        source.video_stream_file = Mock()
        source.video_stream_file.write.side_effect = lambda data: events.append(("write", data))
        source.video_context_clean = Mock(side_effect=lambda encode_thread: events.append(("clean", encode_thread)))
        source.make_draw_packet = Mock(return_value=("draw",))
        source.queue_damage_packet = Mock()
        source.schedule_video_encoder_flush = Mock()
        source.schedule_video_encoder_timer = Mock()

        source.do_flush_video_encoder()

        self.assertEqual(events, [("write", b"data"), ("clean", True)])
        source.video_stream_file.flush.assert_called_once_with()
        source.queue_damage_packet.assert_called_once()
        source.schedule_video_encoder_flush.assert_not_called()
        source.schedule_video_encoder_timer.assert_not_called()

    def test_flush_data_released_for_replaced_encoder(self) -> None:
        # the flush data must not keep a reference to an encoder which has been replaced:
        source = self.make_source()
        old_encoder = Mock()
        old_encoder.is_closed.return_value = False
        source._video_encoder = Mock()
        source.b_frame_flush_data = old_encoder, None, 1, 0, 0, None, False

        source.do_flush_video_encoder()

        self.assertEqual(source.b_frame_flush_data, ())
        old_encoder.flush.assert_not_called()

    def test_flush_data_released_for_closed_encoder(self) -> None:
        source = self.make_source()
        encoder = Mock()
        encoder.is_closed.return_value = True
        source._video_encoder = encoder
        source.b_frame_flush_data = encoder, None, 1, 0, 0, None, False

        source.do_flush_video_encoder()

        self.assertEqual(source.b_frame_flush_data, ())
        encoder.flush.assert_not_called()

    def test_flush_data_released_after_flush(self) -> None:
        source = self.make_source()
        encoder = Mock()
        encoder.is_closed.return_value = False
        encoder.get_type.return_value = "test"
        encoder.get_encoding.return_value = "h264"
        encoder.get_width.return_value = 64
        encoder.get_height.return_value = 64
        encoder.flush.return_value = b"data", {}
        source._video_encoder = encoder
        source.b_frame_flush_data = encoder, None, 1, 0, 0, None, False
        source.b_frame_flush_timer = 0
        source.start_video_frame = 0
        source.video_stream_file = None
        source.make_draw_packet = Mock(return_value=("draw",))
        source.queue_damage_packet = Mock()
        source.schedule_video_encoder_flush = Mock()
        source.schedule_video_encoder_timer = Mock()

        source.do_flush_video_encoder()

        encoder.flush.assert_called_once_with(1)
        self.assertEqual(source.b_frame_flush_data, ())
        source.schedule_video_encoder_timer.assert_called_once_with()


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

    def test_client_properties_exclude_unregistered_encodings(
        self,
    ) -> None:
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
        with patch.object(
            WindowSource, "do_set_client_properties", set_core_encodings,
        ):
            source.do_set_client_properties(properties)

        self.assertEqual(source.non_video_encodings, ("jpeg",))


class ScalingCacheTest(unittest.TestCase):

    def test_candidate_limits_override_generic_scaling(self) -> None:
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
        source.video_helper.get_encoder_specs.return_value = {
            "RGB": (encoder_spec,),
        }
        source._current_quality = 50
        source._fixed_min_quality = 0
        source._current_speed = 50
        source._fixed_min_speed = 0
        source.content_types = ()
        source.is_shadow = False
        source.video_max_size = (4096, 4096)
        source.video_subregion = None
        source.full_csc_modes = typedict({"h264": ("RGB",)})
        source.encoding_options = typedict()
        source._csc_encoder = None
        source._video_encoder = None
        source.matches_video_subregion = Mock(return_value=None)
        source.get_video_fps = Mock(return_value=0)
        source.is_cancelled = Mock(return_value=False)
        source.calculate_scaling = Mock(side_effect=((1, 1), (2, 3)))

        with patch(
            "xpra.server.window.video_pipeline.get_pipeline_score",
            return_value=(1,),
        ) as get_pipeline_score:
            source.get_video_pipeline_options(("h264",), 3000, 2000, "RGB")

        scaling_calls = tuple(call.args for call in source.calculate_scaling.call_args_list)
        self.assertEqual(scaling_calls, (
            (3000, 2000, 4096, 4096),
            (3000, 2000, 2048, 2048),
        ))
        self.assertEqual(get_pipeline_score.call_args.args[5], (2, 3))


def main() -> None:
    unittest.main()


if __name__ == "__main__":
    main()
