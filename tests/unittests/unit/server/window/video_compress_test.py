# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.codecs import openh264
from xpra.codecs.constants import CSCSpec, VideoSpec
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


class VideoQualitySelectionTest(unittest.TestCase):

    def test_high_quality_prefers_vp8_and_vp9_over_current_openh264(self):
        self.enterContext(patch.multiple(openh264, MAX_QUALITY=45, LARGE_FRAME_MAX_QUALITY=35, LARGE_FRAME_PIXELS=1920 * 1080))
        self.enterContext(patch.multiple("xpra.server.window.video_scoring", GPU_BIAS=100, MIN_FPS_COST=4))
        self.enterContext(patch.multiple(
            "xpra.server.window.video_compress", FORCE_CSC=False, PREFERRED_ENCODING_ORDER=("h264", "vp8", "vp9"),
        ))
        h264 = openh264.OpenH264Spec(
            codec_class=object, codec_type="openh264", encoding="h264",
            output_colorspaces=("YUV420P",), quality=40, speed=20, size_efficiency=40,
            setup_cost=0, max_w=3840, max_h=2160,
        )
        vp8 = VideoSpec(codec_class=object, codec_type="vpx", encoding="vp8", output_colorspaces=("YUV420P",),
                        quality=50, speed=50, size_efficiency=60, setup_cost=20)
        vp9 = replace(vp8, encoding="vp9", speed=40)
        encoders = {spec.encoding: {"YUV420P": (spec,)} for spec in (h264, vp8, vp9)}
        converter = CSCSpec(codec_class=object, codec_type="csc", can_scale=True, quality=100, speed=100, setup_cost=0)
        source = WindowVideoSource.__new__(WindowVideoSource)
        source.video_helper = Mock()
        source.video_helper.get_encoder_specs.side_effect = encoders.get
        source.video_helper.get_csc_specs.return_value = {"YUV420P": (converter,)}
        source._fixed_min_quality = 0
        source._current_speed = 50
        source._fixed_min_speed = 0
        source.content_types = ()
        source.is_shadow = False
        source.video_max_size = (4096, 4096)
        source.video_subregion = SimpleNamespace(detection=True)
        source.full_csc_modes = typedict({encoding: ("YUV420P",) for encoding in encoders})
        source.encoding_options = typedict()
        source._csc_encoder = Mock()
        source._csc_encoder.get_type.return_value = "csc"
        source._csc_encoder.get_dst_format.return_value = "YUV420P"
        source._video_encoder = Mock()
        source._video_encoder.get_type.return_value = "openh264"
        source._video_encoder.get_src_format.return_value = "YUV420P"
        source.matches_video_subregion = Mock(return_value=None)
        source.get_video_fps = Mock()
        source.is_cancelled = Mock(return_value=False)
        source.calculate_scaling = Mock(return_value=(1, 1))
        for width, height in ((128, 128), (1920, 1080), (3840, 2160)):
            source._csc_encoder.get_src_width.return_value = width
            source._csc_encoder.get_src_height.return_value = height
            source._video_encoder.get_width.return_value = width
            source._video_encoder.get_height.return_value = height
            for quality in (70, 90, 100):
                source._current_quality = quality
                for fps in (0, 20):
                    source.get_video_fps.return_value = fps
                    with self.subTest(size=(width, height), quality=quality, fps=fps):
                        scores = source.get_video_pipeline_options(("h264", "vp8", "vp9"), width, height, "RGB")
                        by_encoding = {score[-1].encoding: score[0] for score in scores}
                        self.assertGreater(by_encoding["vp8"], by_encoding["h264"])
                        self.assertGreater(by_encoding["vp9"], by_encoding["h264"])
                        self.assertEqual(scores[-1][-1].codec_type, "openh264")


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
            "xpra.server.window.video_compress.get_pipeline_score",
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
