#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import subprocess
import sys
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from xpra.server.window import video_pipeline, video_scoring
from xpra.server.window.video_pipeline import PipelineSettings, PipelineCodecState, get_pipeline_options, get_pipeline_quality
from unit.server.window.video_pipeline_test_util import encoder_spec, csc_spec, current_encoder, current_csc


class PipelineQualityTest(unittest.TestCase):

    def test_video_quality_reduction_bounds_and_rounding(self):
        for quality, minimum, fps, expected in (
            (50, 0, 0, 50), (50, 0, 1, 49), (51, 0, 1, 49),
            (50, 0, 44, 6), (50, 0, 45, 5), (50, 0, 100, 5),
            (50, 40, 30, 40), (0, 0, 20, 0),
        ):
            with self.subTest(quality=quality, minimum=minimum, fps=fps):
                self.assertEqual(get_pipeline_quality(quality, minimum, fps), expected)

    def test_nonvideo_quality_raise_preserves_rounding(self):
        for quality, expected in ((0, 0), (1, 10), (25, 50), (50, 70), (99, 99), (100, 100)):
            with self.subTest(quality=quality):
                self.assertEqual(get_pipeline_quality(quality, 0, None), expected)


class VideoPipelineTest(unittest.TestCase):
    settings = PipelineSettings(quality=50, min_quality=0, speed=50, min_speed=0, max_size=(4096, 4096),
                                text_hint=False, is_shadow=False, force_csc=False, force_csc_mode="",
                                preferred_encodings=("h264", "vp9"))

    def setUp(self):
        scoring = patch.multiple(video_scoring, GPU_BIAS=100, MIN_FPS_COST=4)
        scoring.start()
        self.addCleanup(scoring.stop)
        self.encoder = encoder_spec()
        self.encoders = {"h264": {"RGB": (self.encoder,)}}
        self.converters = {}
        self.formats = {"h264": ("RGB", "YUV420P", "YUV444P")}
        self.specs = Mock()
        self.specs.get_csc_specs.side_effect = lambda fmt: self.converters
        self.specs.get_encoder_specs.side_effect = lambda encoding: self.encoders.get(encoding)
        self.scaling = Mock(return_value=(1, 1))
        self.cancelled = Mock(return_value=False)
        self.codec_state = Mock(return_value=PipelineCodecState())

    def select(self, settings=None, encodings=("h264",), width=640, height=480, src_format="RGB", score_deltas=None, fps=20):
        return get_pipeline_options(encodings, width, height, src_format, settings or self.settings, self.specs,
                                    lambda encoding: self.formats.get(encoding, ()), score_deltas or {},
                                    self.scaling, self.cancelled, self.codec_state, fps)

    def test_direct_candidate_and_empty_inputs(self):
        result, = self.select()
        self.assertEqual(result.score, 321)
        self.assertIs(result.encoder_spec, self.encoder)
        self.assertIsNone(result.csc_spec)
        self.assertEqual(self.select(encodings=()), ())
        self.assertEqual(self.select(encodings=("missing",)), ())
        self.formats["missing"] = ("RGB",)
        self.assertEqual(self.select(encodings=("missing",)), ())

    def test_missing_input_or_output_format(self):
        self.assertEqual(self.select(src_format="RGBX"), ())
        self.formats["h264"] = ("unsupported",)
        self.assertEqual(self.select(), ())
        self.codec_state.assert_not_called()

    def test_forced_csc_filters_candidates(self):
        self.encoders["h264"]["YUV420P"] = (self.encoder,)
        self.encoders["h264"]["YUV444P"] = (self.encoder,)
        self.converters.update({"YUV420P": (csc_spec("420"),), "YUV444P": (csc_spec("444"),)})
        settings = replace(self.settings, force_csc=True, force_csc_mode="YUV420P")
        result, = self.select(settings)
        self.assertEqual(result.enc_in_format, "YUV420P")
        self.assertIs(result.csc_spec, self.converters["YUV420P"][0])
        self.assertEqual(len(self.select(settings, src_format="YUV420P")), 2)
        self.assertEqual(self.select(replace(settings, force_csc_mode="NV12")), ())

    def test_stable_ties_keep_input_and_spec_order(self):
        second = encoder_spec("second")
        self.encoders["h264"]["RGB"] = (self.encoder, second)
        self.encoders["vp9"] = {"RGB": (second,)}
        self.formats["vp9"] = ("RGB",)
        scores = self.select(encodings=iter(("vp9", "h264")), score_deltas={"h264.score-delta": 0})
        self.assertEqual(tuple(s.encoder_spec for s in scores), (second, self.encoder, second))
        self.assertEqual(tuple(s.score for s in scores), (320, 320, 320))

    def test_unknown_preferences_and_explicit_score_delta(self):
        settings = replace(self.settings, preferred_encodings=())
        self.assertEqual(self.select(settings)[0].score, 320)
        self.assertEqual(self.select(settings, score_deltas={"h264.score-delta": 90})[0].score, 410)

    def test_scaling_capabilities_determine_owner(self):
        for csc, encoder, expected_csc, expected_encoder in (
            (False, False, (1, 1), (1, 1)),
            (True, False, (1, 2), (1, 1)),
            (False, True, (1, 1), (1, 2)),
            (True, True, (1, 2), (1, 1)),
        ):
            with self.subTest(csc=csc, encoder=encoder):
                self.encoder.can_scale = encoder
                converter = csc_spec(can_scale=csc)
                self.encoders["h264"] = {"YUV420P": (self.encoder,)}
                self.converters = {"YUV420P": (converter,)}
                self.scaling.return_value = (1, 2)
                score, = self.select()
                self.assertEqual(score.csc_scaling, expected_csc)
                self.assertEqual(score.encoder_scaling, expected_encoder)
                self.assertEqual((score.enc_width, score.enc_height), (320, 240) if csc or encoder else (640, 480))

    def test_direct_encoder_scaling(self):
        self.encoder.can_scale = True
        self.scaling.return_value = (2, 3)
        score, = self.select()
        self.assertIsNone(score.csc_scaling)
        self.assertEqual(score.encoder_scaling, (2, 3))
        # Direct encoder scaling uses source dimensions in the existing score tuple.
        self.assertEqual((score.enc_width, score.enc_height), (640, 480))

    def test_generic_scaling_cache_and_candidate_limits(self):
        self.encoder.can_scale = True
        self.encoder.max_w, self.encoder.max_h = 2048, 1024
        self.encoders["h264"] = {"YUV420P": (self.encoder,)}
        self.converters = {"YUV420P": (csc_spec(),)}
        self.scaling.side_effect = ((1, 1), (1, 2))
        result, = self.select(width=3000, height=2000)
        self.assertEqual(result.scaling, (1, 2))
        self.assertEqual(tuple(call.args for call in self.scaling.call_args_list), (
            (3000, 2000, 4096, 4096), (3000, 2000, 2048, 1024),
        ))

    def test_scaling_cache_boundaries_and_separate_dimension_limits(self):
        self.encoder.can_scale = True
        self.encoder.max_w = self.encoder.max_h = 10000
        for width, height, max_size, expected_calls in (
            (4096, 4096, (10000, 10000), 1), (4097, 4000, (10000, 10000), 2),
            (4000, 4097, (10000, 10000), 2), (2048, 1025, (2048, 1024), 2),
            (2049, 1024, (2048, 1024), 2), (2048, 1024, (2048, 1024), 1),
        ):
            with self.subTest(size=(width, height), max_size=max_size):
                self.scaling.reset_mock()
                self.select(replace(self.settings, max_size=max_size), width=width, height=height)
                self.assertEqual(self.scaling.call_count, expected_calls)

    def test_text_overrides_video_size_limits(self):
        self.encoder.can_scale = True
        self.encoder.max_w = self.encoder.max_h = 20000
        self.select(replace(self.settings, text_hint=True, max_size=(100, 100)), width=17000, height=17000)
        self.assertEqual(self.scaling.call_args.args, (17000, 17000, 16384, 16384))

    def test_non_scaling_encoder_does_not_use_generic_ratio(self):
        self.scaling.return_value = (1, 2)
        score, = self.select()
        self.assertEqual(score.scaling, (1, 1))

    def test_masks_and_minimum_maximum_dimensions(self):
        self.encoder.width_mask, self.encoder.height_mask = 0xFFFE, 0xFFFC
        self.encoder.min_w, self.encoder.min_h = 32, 32
        self.encoder.max_w, self.encoder.max_h = 640, 480
        for width, height, accepted in ((31, 32, False), (32, 31, False), (32, 32, True),
                                        (641, 483, True), (642, 480, False), (640, 484, False)):
            with self.subTest(size=(width, height)):
                scores = self.select(width=width, height=height)
                self.assertEqual(bool(scores), accepted)
                if accepted:
                    self.assertEqual((scores[0].enc_width, scores[0].enc_height), (width & 0xFFFE, height & 0xFFFC))

    def test_csc_masks_are_combined_with_encoder_masks(self):
        self.encoder.width_mask, self.encoder.height_mask = 0xFFFE, 0xFFFE
        self.encoders["h264"] = {"YUV420P": (self.encoder,)}
        self.converters = {"YUV420P": (csc_spec(width_mask=0xFFFC, height_mask=0xFFF8),)}
        score, = self.select(width=647, height=487)
        self.assertEqual((score.csc_width, score.csc_height, score.enc_width, score.enc_height), (644, 480, 644, 480))

    def test_lossy_and_scaling_penalties(self):
        self.encoder.can_scale = True
        for src_format, scaling, text, quality, shadow, penalty in (
            ("RGB", (1, 1), True, 100, True, 0),
            ("RGB", (1, 2), True, 100, False, -500),
            ("RGB", (1, 2), False, 100, False, -250),
            ("YUV420P", (1, 1), True, 50, False, -500),
            ("YUV422P", (1, 1), False, 100, False, -250),
            ("NV12", (1, 1), False, 50, True, -40),
            ("NV12", (1, 2), False, 50, True, 0),
        ):
            with self.subTest(src_format=src_format, scaling=scaling, text=text, quality=quality, shadow=shadow):
                self.encoders["h264"] = {src_format: (self.encoder,)}
                self.scaling.return_value = scaling
                settings = replace(self.settings, text_hint=text, quality=quality, is_shadow=shadow)
                with patch.object(video_pipeline, "get_pipeline_score", wraps=video_scoring.get_pipeline_score) as scorer:
                    self.select(settings, src_format=src_format)
                self.assertEqual(scorer.call_args.args[12], 1 + penalty)

    def test_current_codecs_and_runtime_factors_change_ranking(self):
        other = encoder_spec("other", setup_cost=0)
        self.encoders["h264"]["RGB"] = (other, self.encoder)
        self.codec_state.return_value = PipelineCodecState(encoder=current_encoder(self.encoder), detection=True)
        self.assertIs(self.select()[0].encoder_spec, other)
        # The reused codec avoids its setup cost; a boost only applies to new encoders.
        self.encoder.score_boost = 1000
        self.assertIs(self.select()[0].encoder_spec, other)
        self.codec_state.return_value = PipelineCodecState(detection=True)
        self.assertIs(self.select()[0].encoder_spec, self.encoder)
        with patch.object(self.encoder, "get_runtime_factor", return_value=0):
            self.assertIs(self.select()[0].encoder_spec, other)

    def test_csc_reuse_and_runtime_factor(self):
        converter = csc_spec()
        self.encoders["h264"] = {"YUV420P": (self.encoder,)}
        self.converters = {"YUV420P": (converter,)}
        self.codec_state.return_value = PipelineCodecState(detection=True)
        original, = self.select()
        self.codec_state.return_value = PipelineCodecState(csc=current_csc(converter), detection=True)
        reused, = self.select()
        self.assertGreater(reused.score, original.score)
        with patch.object(converter, "get_runtime_factor", return_value=0):
            self.assertEqual(self.select()[0].score, 0)

    def test_csc_changes_keep_setup_cost(self):
        converter = csc_spec()
        self.encoders["h264"] = {"YUV420P": (self.encoder,)}
        self.converters = {"YUV420P": (converter,)}
        self.codec_state.return_value = PipelineCodecState(detection=True)
        original, = self.select()
        for changes in ({"dst_format": "YUV444P"}, {"width": 642}, {"height": 482}):
            with self.subTest(changes=changes):
                changed = current_csc(converter, **changes)
                self.codec_state.return_value = PipelineCodecState(csc=changed, detection=True)
                self.assertEqual(self.select()[0], original)
        changed = current_csc(csc_spec("other"))
        self.codec_state.return_value = PipelineCodecState(csc=changed, detection=True)
        self.assertEqual(self.select()[0], original)

    def test_fps_affects_setup_cost_only_with_detection(self):
        high, = self.select(fps=20)
        low, = self.select(fps=0)
        self.assertEqual(high, low)
        self.codec_state.return_value = PipelineCodecState(detection=True)
        high, = self.select(fps=20)
        low, = self.select(fps=0)
        self.assertGreater(high.score, low.score)

    def test_cancellation_retains_already_scored_candidates(self):
        self.encoders["h264"]["RGB"] = (self.encoder, encoder_spec("second"))
        self.cancelled.side_effect = (False, True)
        scores = self.select()
        self.assertEqual(len(scores), 1)
        self.assertIs(scores[0].encoder_spec, self.encoder)
        self.assertEqual(self.cancelled.call_count, 2)
        self.codec_state.assert_called_once_with()

    def test_selection_imports_without_gui_or_codec_plugins(self):
        script = """
import sys
from xpra.server.window import video_pipeline
assert 'gi' not in sys.modules
assert 'xpra.server.window.video_compress' not in sys.modules
assert not any(name.startswith(('xpra.codecs.enc_', 'xpra.codecs.csc_')) for name in sys.modules)
"""
        result = subprocess.run((sys.executable, "-c", script), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
