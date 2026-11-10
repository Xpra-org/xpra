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


class VideoFrameLostTest(unittest.TestCase):
    """ the client lost some or all of the fragments of a frame sent as datagrams """

    @staticmethod
    def make_source(encoder) -> WindowVideoSource:
        from xpra.server.window.perfstats import WindowPerformanceStatistics
        source = WindowVideoSource.__new__(WindowVideoSource)
        source.wid = 1
        source._video_encoder = encoder
        source.statistics = WindowPerformanceStatistics()
        source.global_statistics = Mock(min_client_latency=0.01)
        source.jitter = 0
        source.bandwidth_limit = 0
        source.networksend_congestion_event = Mock()
        source.frame_losses = {"lost": 0, "partial": 0}
        source._damage_delayed = None
        source.decode_error_refresh_timer = 0
        source.video_context_clean = Mock()
        source.client_decode_error = Mock()
        return source

    @staticmethod
    def send(source, sequence: int, pts: int) -> None:
        # pending = (now, coding, pixcount, bytecount, client_options, damage_time)
        source.statistics.damage_ack_pending[sequence] = (0, "h264", 100, 100, {"frame": sequence, "pts": pts}, 0)

    def test_lost_frame_requests_recovery(self) -> None:
        from xpra.constants import WINDOW_DECODE_LOST
        encoder = Mock()
        source = self.make_source(encoder)
        self.send(source, 5, 200)
        source.damage_packet_acked(5, 64, 32, WINDOW_DECODE_LOST, "lost", {"missing": (0, 1), "fragments": 2})
        encoder.request_recovery.assert_called_once_with(200)
        self.assertEqual(source.frame_losses, {"lost": 1, "partial": 0})
        self.assertNotIn(5, source.statistics.damage_ack_pending)
        # this is not a decoding error, the video context is kept:
        source.client_decode_error.assert_not_called()
        source.video_context_clean.assert_not_called()

    def test_partial_frame_requests_recovery(self) -> None:
        encoder = Mock()
        source = self.make_source(encoder)
        self.send(source, 6, 240)
        source.damage_packet_acked(6, 64, 32, 1500, "", {"missing": (3, ), "fragments": 8})
        encoder.request_recovery.assert_called_once_with(240)
        self.assertEqual(source.frame_losses, {"lost": 0, "partial": 1})

    def test_complete_frame(self) -> None:
        encoder = Mock()
        source = self.make_source(encoder)
        self.send(source, 7, 280)
        source.damage_packet_acked(7, 64, 32, 1500, "", {})
        encoder.request_recovery.assert_not_called()
        self.assertEqual(source.frame_losses, {"lost": 0, "partial": 0})

    def test_encoder_without_recovery(self) -> None:
        from xpra.constants import WINDOW_DECODE_LOST
        encoder = Mock(spec=["get_type"])
        source = self.make_source(encoder)
        self.send(source, 8, 320)
        source.damage_packet_acked(8, 64, 32, WINDOW_DECODE_LOST, "lost")
        # the only way to recover is a new stream:
        source.video_context_clean.assert_called_once_with()


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
        source.schedule_video_encoder_timer.assert_called_once_with(encoder, None)


class VideoEncodeTest(unittest.TestCase):

    def test_grayscale_conversion(self) -> None:
        if load_codec("csc_libyuv") is None:
            self.skipTest("libyuv converter is not available")

        pixels = bytes((0, 0, 255, 255, 0, 255, 0, 255, 255, 0, 0, 255, 50, 100, 200, 255))
        image = ImageWrapper(0, 0, 2, 2, (pixels,), "BGRX", 24, 8)
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
        gray_pixels = bytes(converted.get_plane(0))
        self.assertEqual(len(gray_pixels), len(pixels))
        self.assertNotEqual(gray_pixels, pixels)
        for offset in range(0, len(gray_pixels), 4):
            b, g, r = gray_pixels[offset:offset + 3]
            self.assertEqual(b, g)
            self.assertEqual(g, r)


class VideoEncoderOptionsTest(unittest.TestCase):

    def test_scroll_hint_expires_after_one_second(self) -> None:
        source = WindowVideoSource.__new__(WindowVideoSource)
        source.last_scroll_time = 0
        source.cuda_device_context = None
        source._fixed_quality = source._fixed_speed = 50
        source.content_types = ("browser",)
        for event, now, expected in ((10, 10, 0), (10, 10.25, 250), (10, 10.9999, 999),
                                     (10, 11, None), (10, 12, None), (10, 9, None), (0, 0.5, None)):
            with self.subTest(event=event, now=now):
                source.last_scroll_event = event
                with patch("xpra.server.window.video_compress.monotonic", return_value=now):
                    options = source.get_video_encoder_options("h264", 640, 480)
                if expected is None:
                    self.assertNotIn("scroll-age-ms", options)
                else:
                    self.assertEqual(options["scroll-age-ms"], expected)


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
