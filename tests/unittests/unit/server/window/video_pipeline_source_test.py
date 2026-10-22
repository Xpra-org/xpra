#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.server.window import video_compress, video_pipeline, video_scoring
from xpra.server.window.video_scoring import get_pipeline_score
from unit.server.window.video_pipeline_test_util import encoder_spec, csc_spec, make_source, current_encoder, current_csc


class VideoPipelineSourceTest(unittest.TestCase):

    def setUp(self):
        self.settings = patch.multiple(video_compress, FORCE_CSC=False, FORCE_CSC_MODE="", PREFERRED_ENCODING_ORDER=("h264", "vp9"))
        self.settings.start()
        self.addCleanup(self.settings.stop)
        scoring = patch.multiple(video_scoring, GPU_BIAS=100, MIN_FPS_COST=4)
        scoring.start()
        self.addCleanup(scoring.stop)

    @staticmethod
    def select(source, encodings=("h264",), width=640, height=480, src_format="RGB"):
        return source.get_video_pipeline_options(encodings, width, height, src_format)

    def test_direct_score_and_cache(self):
        spec = encoder_spec()
        source = make_source({"h264": {"RGB": (spec,)}})
        with patch.object(video_compress, "monotonic", return_value=123):
            scores = self.select(source)
        self.assertEqual(scores, ((321, (1, 1), None, 0, 0, None, "RGB", (1, 1), 640, 480, spec),))
        self.assertIs(source.last_pipeline_scores, scores)
        self.assertEqual(source.last_pipeline_params, (("h264",), 640, 480, "RGB"))
        self.assertEqual(source.last_pipeline_time, 123)
        source.calculate_scaling.assert_called_once_with(640, 480, 4096, 4096)

    def test_closed_helper_keeps_previous_cache(self):
        source = make_source()
        source.video_helper = None
        self.assertEqual(self.select(source), ())
        self.assertEqual(source.last_pipeline_scores, ("old",))
        self.assertEqual(source.last_pipeline_params, ("old",))
        self.assertEqual(source.last_pipeline_time, 10)
        source.calculate_scaling.assert_not_called()

    def test_no_client_formats_or_encoder_specs(self):
        source = make_source()
        source.full_csc_modes["h264"] = ()
        self.assertEqual(self.select(source), ())
        source.video_helper.get_encoder_specs.assert_not_called()
        source = make_source({})
        self.assertEqual(self.select(source), ())
        self.assertEqual(source.last_pipeline_scores, ())

    def test_output_formats_must_match_client(self):
        source = make_source()
        source.full_csc_modes["h264"] = ("unsupported",)
        self.assertEqual(self.select(source), ())
        # Unsupported output formats short circuit the candidate cancellation check.
        self.assertEqual(source.is_cancelled.call_count, 1)

    def test_direct_and_csc_candidates_preserve_spec_identity(self):
        direct, converted = encoder_spec("direct"), encoder_spec("converted")
        converter = csc_spec()
        source = make_source({"h264": {"RGB": (direct,), "YUV420P": (converted,)}}, {"YUV420P": (converter,)})
        scores = self.select(source)
        self.assertEqual(tuple(s[-1] for s in scores), (direct, converted))
        self.assertIsNone(scores[0][5])
        self.assertIs(scores[1][5], converter)
        self.assertEqual(scores[1][6], "YUV420P")

    def test_missing_encoder_input_formats(self):
        source = make_source({"h264": {"NV12": (encoder_spec(),)}}, {"YUV420P": (csc_spec(),)})
        self.assertEqual(self.select(source), ())

    def test_forced_csc_and_matching_direct_source(self):
        spec = encoder_spec()
        source = make_source({"h264": {"RGB": (spec,), "YUV420P": (spec,), "YUV444P": (spec,)}},
                             {"YUV420P": (csc_spec("420"),), "YUV444P": (csc_spec("444"),)})
        with patch.multiple(video_compress, FORCE_CSC=True, FORCE_CSC_MODE="YUV420P"):
            scores = self.select(source)
            self.assertEqual(tuple(s[6] for s in scores), ("YUV420P",))
            scores = self.select(source, src_format="YUV420P")
            self.assertEqual(tuple(s[6] for s in scores), ("YUV420P", "YUV420P"))
            self.assertIsNone(scores[0][5])

    def test_forced_missing_csc_has_no_candidates(self):
        source = make_source()
        with patch.multiple(video_compress, FORCE_CSC=True, FORCE_CSC_MODE="NV12"):
            self.assertEqual(self.select(source), ())

    def test_preference_override_and_stable_ties(self):
        first, second = encoder_spec("first"), encoder_spec("second")
        other = encoder_spec("other")
        source = make_source({"h264": {"RGB": (first, second)}, "vp9": {"RGB": (other,)}})
        source.full_csc_modes["vp9"] = ("RGB",)
        scores = self.select(source, ("vp9", "h264"))
        self.assertEqual(tuple(s[-1] for s in scores), (first, second, other))
        source.encoding_options["vp9.score-delta"] = 1
        scores = self.select(source, ("vp9", "h264"))
        self.assertEqual(tuple(s[-1] for s in scores), (other, first, second))
        source.encoding_options["vp9.score-delta"] = 100
        self.assertIs(self.select(source, ("h264", "vp9"))[0][-1], other)

    def test_unknown_encoding_has_zero_preference_bonus(self):
        spec = encoder_spec()
        source = make_source({"custom": {"RGB": (spec,)}})
        source.full_csc_modes["custom"] = ("RGB",)
        self.assertEqual(self.select(source, ("custom",))[0][0], 320)

    def test_quality_adjustment_for_subregions(self):
        for quality, minimum, fps, is_video, expected in (
            (50.9, 0, 20, True, 30), (50, 40, 20, True, 40),
            (50, 0, 60, True, 5), (50, 0, 0, True, 50),
            (50, 0, 20, False, 70), (99, 0, 20, False, 99),
        ):
            with self.subTest(quality=quality, minimum=minimum, fps=fps, is_video=is_video):
                source = make_source()
                source._current_quality = quality
                source._fixed_min_quality = minimum
                source.matches_video_subregion.return_value = object()
                source.subregion_is_video.return_value = is_video
                source.video_subregion = SimpleNamespace(fps=fps, detection=True)
                with patch.object(video_pipeline, "get_pipeline_score", wraps=get_pipeline_score) as scorer:
                    self.select(source)
                self.assertEqual(scorer.call_args.args[6:10], (expected, minimum, 50, 0))

    def test_text_and_lossless_skip_subregion_quality_adjustment(self):
        for text, quality in ((True, 50), (False, 100)):
            with self.subTest(text=text, quality=quality):
                source = make_source()
                source._current_quality = quality
                source.content_types = ("text",) if text else ()
                source.matches_video_subregion.return_value = object()
                with patch.object(video_pipeline, "get_pipeline_score", wraps=get_pipeline_score) as scorer:
                    self.select(source)
                source.subregion_is_video.assert_not_called()
                self.assertEqual(scorer.call_args.args[6], quality)

    def test_subsampling_and_shadow_penalties(self):
        for text, quality, shadow, expected_delta in (
            (False, 50, False, 1), (True, 50, False, -499),
            (False, 100, False, -249), (False, 50, True, -39),
            (True, 100, True, -539),
        ):
            with self.subTest(text=text, quality=quality, shadow=shadow):
                source = make_source({"h264": {"YUV420P": (encoder_spec(),)}})
                source._current_quality = quality
                source.content_types = ("text",) if text else ()
                source.is_shadow = shadow
                with patch.object(video_pipeline, "get_pipeline_score", wraps=get_pipeline_score) as scorer:
                    self.select(source, src_format="YUV420P")
                self.assertEqual(scorer.call_args.args[12], expected_delta)

    def test_scaling_penalty_and_shadow_subsampling_exception(self):
        for text, quality, src_format, expected_delta in (
            (False, 50, "YUV420P", 1), (True, 50, "RGB", -499), (False, 100, "RGB", -249),
        ):
            with self.subTest(text=text, quality=quality, src_format=src_format):
                source = make_source({"h264": {src_format: (encoder_spec(can_scale=True),)}})
                source.calculate_scaling.return_value = (1, 2)
                source.is_shadow = True
                source._current_quality = quality
                source.content_types = ("text",) if text else ()
                with patch.object(video_pipeline, "get_pipeline_score", wraps=get_pipeline_score) as scorer:
                    self.select(source, src_format=src_format)
                self.assertEqual(scorer.call_args.args[12], expected_delta)

    def test_video_limits_and_text_override(self):
        for text, expected_limits in ((False, (1024, 768)), (True, (16384, 16384))):
            with self.subTest(text=text):
                source = make_source({"h264": {"RGB": (encoder_spec(can_scale=True, max_w=20000, max_h=20000),)}})
                source.video_max_size = (1024, 768)
                source.content_types = ("text",) if text else ()
                self.select(source, width=17000, height=17000)
                self.assertEqual(source.calculate_scaling.call_args.args, (17000, 17000, *expected_limits))

    def test_live_codec_state_read_for_each_candidate(self):
        spec = encoder_spec()
        source = make_source({"h264": {"YUV420P": (spec, spec)}}, {"YUV420P": (csc_spec(),)})
        changed_csc, changed_encoder = object(), object()

        def score(*args):
            source._csc_encoder = changed_csc
            source._video_encoder = changed_encoder
            source.video_subregion = SimpleNamespace(detection=True)
            return (1,)

        with patch.object(video_pipeline, "get_pipeline_score", side_effect=score) as scorer:
            self.select(source)
        first, second = scorer.call_args_list
        self.assertEqual(first.args[10:12], (None, None))
        self.assertFalse(first.args[14])
        self.assertEqual(second.args[10:12], (changed_csc, changed_encoder))
        self.assertTrue(second.args[14])

    def test_existing_codec_switching_costs(self):
        spec, converter = encoder_spec(), csc_spec()
        source = make_source({"h264": {"YUV420P": (spec,)}}, {"YUV420P": (converter,)})
        initial_score = self.select(source)[0][0]
        source.video_subregion = SimpleNamespace(detection=True)
        new_pipeline_score = self.select(source)[0][0]
        source._video_encoder = current_encoder(spec, src_format="YUV420P")
        source._csc_encoder = current_csc(converter)
        reused_pipeline_score = self.select(source)[0][0]
        self.assertLess(new_pipeline_score, initial_score)
        self.assertGreater(reused_pipeline_score, new_pipeline_score)

    def test_cancelled_before_scoring_clears_cache(self):
        source = make_source()
        source.is_cancelled.return_value = True
        with patch.object(video_compress, "monotonic", return_value=456):
            self.assertEqual(self.select(source), ())
        self.assertEqual(source.last_pipeline_scores, ())
        self.assertEqual(source.last_pipeline_params, ())
        self.assertEqual(source.last_pipeline_time, 456)

    def test_cancelled_during_enumeration_returns_partial_result(self):
        first, second = encoder_spec("first"), encoder_spec("second")
        source = make_source({"h264": {"RGB": (first, second)}})
        source.is_cancelled.side_effect = (False, True, True)
        scores = self.select(source)
        self.assertEqual(len(scores), 1)
        self.assertIs(scores[0][-1], first)
        self.assertEqual(source.last_pipeline_scores, ())
        self.assertEqual(source.last_pipeline_params, ())

    def test_final_cancellation_prevents_cache_publication(self):
        source = make_source()
        source.is_cancelled.side_effect = (False, True)
        self.assertEqual(len(self.select(source)), 1)
        self.assertEqual(source.last_pipeline_scores, ())
        self.assertEqual(source.last_pipeline_params, ())

    def test_rejected_score_is_omitted(self):
        source = make_source({"h264": {"RGB": (encoder_spec(min_w=641),)}})
        self.assertEqual(self.select(source), ())

    def test_selected_named_and_ordinary_tuples_verify_existing_codecs(self):
        spec, converter = encoder_spec(), csc_spec()
        for use_csc in (False, True):
            source = make_source({"h264": {"YUV420P": (spec,)}}, {"YUV420P": (converter,)} if use_csc else {})
            score, = self.select(source, src_format="RGB" if use_csc else "YUV420P")
            source._video_encoder = current_encoder(spec, src_format="YUV420P")
            source._csc_encoder = current_csc(converter) if use_csc else None
            source.actual_scaling = (1, 1)
            for candidate in (score, tuple(score)):
                with self.subTest(use_csc=use_csc, named=hasattr(candidate, "score")):
                    source.last_pipeline_scores = (candidate,)
                    self.assertTrue(source.verify_csc_and_encoder())
                    source.actual_scaling = (1, 2)
                    self.assertFalse(source.verify_csc_and_encoder())
                    source.actual_scaling = (1, 1)

    def test_lossless_pipeline_setup_filters_negative_scores(self):
        for positive_score in (0, 1, None):
            with self.subTest(positive_score=positive_score):
                source = make_source()
                score, = self.select(source)
                negative = score._replace(score=-1)
                positive = score._replace(score=positive_score) if positive_score is not None else None
                source.get_video_pipeline_options = Mock(return_value=(negative, positive) if positive else (negative,))
                source.do_check_pipeline = Mock(return_value=False)
                source.csc_clean = Mock()
                source.ve_clean = Mock()
                source.setup_pipeline = Mock(return_value=True)
                source.width_mask = source.height_mask = 0xFFFF
                source._current_quality = 100
                self.assertEqual(source.check_pipeline(("h264",), 640, 480, "RGB"), positive is not None)
                if positive is None:
                    source.setup_pipeline.assert_not_called()
                else:
                    source.setup_pipeline.assert_called_once_with((positive,), 640, 480, "RGB")


if __name__ == "__main__":
    unittest.main()
