#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# ABOUTME: Tests that verify_csc_and_encoder detects scaling changes.
# ABOUTME: Reproduces a bug where scaling=(1,2) was never recovered to (1,1).

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.util.objects import AdHocStruct
from xpra.server.window import video_compress
from xpra.server.window.video_compress import WindowVideoSource


def make_encoder_spec(codec_type="nvenc"):
    spec = AdHocStruct()
    spec.codec_type = codec_type
    return spec


def make_video_encoder(codec_type="nvenc", src_format="BGRX", width=2560, height=1440):
    ve = AdHocStruct()
    ve.get_type = lambda: codec_type
    ve.get_src_format = lambda: src_format
    ve.get_width = lambda: width
    ve.get_height = lambda: height
    ve.is_closed = lambda: False
    return ve


def make_score_tuple(encoder_scaling=(1, 1), enc_in_format="BGRX",
                     enc_width=2560, enc_height=1440, encoder_spec=None, score=423):
    """Build a pipeline candidate consumed by WindowVideoSource."""
    if encoder_spec is None:
        encoder_spec = make_encoder_spec()
    scaling = encoder_scaling
    csc_scaling = None
    csc_width = 0
    csc_height = 0
    csc_spec = None
    return (score, scaling, csc_scaling, csc_width, csc_height, csc_spec,
            enc_in_format, encoder_scaling, enc_width, enc_height, encoder_spec)


def verify_csc_and_encoder(video_encoder, csc_encoder, actual_scaling, scores):
    source = WindowVideoSource.__new__(WindowVideoSource)
    source._video_encoder = video_encoder
    source._csc_encoder = csc_encoder
    source.actual_scaling = actual_scaling
    source.last_pipeline_scores = scores
    return source.verify_csc_and_encoder()


class TestVerifyScaling(unittest.TestCase):

    def test_same_scaling_returns_true(self):
        """Encoder at (1,1) matches best option at (1,1)."""
        ve = make_video_encoder(width=2560, height=1440)
        scores = [make_score_tuple(encoder_scaling=(1, 1))]
        self.assertTrue(verify_csc_and_encoder(ve, None, (1, 1), scores))

    def test_scaling_mismatch_detected(self):
        """
        Current pipeline uses (1,2) but best option wants (1,1).
        Input width/height are both 2560x1440 so without scaling check this was missed.
        """
        ve = make_video_encoder(width=2560, height=1440)
        scores = [make_score_tuple(encoder_scaling=(1, 1))]
        self.assertFalse(verify_csc_and_encoder(ve, None, (1, 2), scores))

    def test_both_downscaled_returns_true(self):
        """Both current and best option use (1,2) — no change needed."""
        ve = make_video_encoder(width=2560, height=1440)
        scores = [make_score_tuple(encoder_scaling=(1, 2))]
        self.assertTrue(verify_csc_and_encoder(ve, None, (1, 2), scores))

    def test_no_encoder_scaling_change(self):
        """No video encoder active, but scaling changed — should trigger rebuild."""
        scores = [make_score_tuple(encoder_scaling=(1, 1))]
        self.assertFalse(verify_csc_and_encoder(None, None, (1, 2), scores))

    def test_no_scores(self):
        """No pipeline scores — should return False."""
        ve = make_video_encoder()
        self.assertFalse(verify_csc_and_encoder(ve, None, (1, 1), []))

    def test_encoder_type_mismatch(self):
        """Different encoder type should trigger rebuild."""
        ve = make_video_encoder(codec_type="x264")
        scores = [make_score_tuple(encoder_scaling=(1, 1))]
        self.assertFalse(verify_csc_and_encoder(ve, None, (1, 1), scores))

    def test_upscale_to_downscale_detected(self):
        """Switching from no scaling to downscaling should be detected."""
        ve = make_video_encoder(width=2560, height=1440)
        scores = [make_score_tuple(encoder_scaling=(1, 2))]
        self.assertFalse(verify_csc_and_encoder(ve, None, (1, 1), scores))


class TestCalculateScaling(unittest.TestCase):

    def setUp(self):
        settings = patch.multiple(
            video_compress, SCALING=True, SCALING_HARDCODED=None,
            SCALING_OPTIONS=video_compress.DEFAULT_SCALING_OPTIONS,
            SCALING_PPS_TARGET=25*1920*1080, SCALING_MIN_PPS=25*320*240,
            DOWNSCALE=True, DOWNSCALE_THRESHOLD=20, TEXT_QUALITY=100,
        )
        settings.start()
        self.addCleanup(settings.stop)
        clock = patch.object(video_compress, "monotonic", return_value=1024)
        clock.start()
        self.addCleanup(clock.stop)

    @staticmethod
    def make_source(**changes):
        source = WindowVideoSource.__new__(WindowVideoSource)
        state = dict(
            client_render_size=(0, 0), scaling_control=None, scaling=None, actual_scaling=(1, 1),
            statistics=SimpleNamespace(last_resized=0, damage_events_count=100),
            last_scroll_time=0, last_pipeline_time=0, content_types=("video",),
            _current_quality=40, _current_speed=50, bandwidth_limit=0,
            is_shadow=False, image_depth=24, fullscreen=False, maximized=False,
            matches_video_subregion=Mock(return_value=True), subregion_is_video=Mock(return_value=True),
            get_video_fps=Mock(return_value=60),
        )
        state.update(changes)
        source.__dict__.update(state)
        return source

    def test_wrapper_measures_video_and_honors_codec_limits(self):
        source = self.make_source()
        self.assertEqual(source.calculate_scaling(1920, 1080), (1, 3))
        source.get_video_fps.assert_called_once_with(1920, 1080)
        source.matches_video_subregion.assert_called_once_with(1920, 1080)
        # Explicit video content short-circuits the subregion classification.
        source.subregion_is_video.assert_not_called()
        source._current_quality = 100
        self.assertEqual(source.calculate_scaling(3000, 2000, 2048, 2048), (2, 3))

    def test_wrapper_uses_subregion_classification(self):
        source = self.make_source(content_types=())
        self.assertEqual(source.calculate_scaling(1920, 1080), (1, 3))
        source.subregion_is_video.assert_called_once_with()
        source.subregion_is_video.reset_mock()
        source.matches_video_subregion.return_value = False
        self.assertEqual(source.calculate_scaling(1920, 1080), (1, 2))
        source.subregion_is_video.assert_not_called()

    def test_wrapper_passes_scaling_settings(self):
        source = self.make_source(client_render_size=(960, 540))
        self.assertEqual(source.calculate_scaling(1920, 1080), (1, 4))
        with patch.object(video_compress, "DOWNSCALE", False):
            self.assertEqual(source.calculate_scaling(1920, 1080), (1, 3))
        with patch.object(video_compress, "SCALING_HARDCODED", (1, 5)):
            self.assertEqual(source.calculate_scaling(1920, 1080), (1, 2))
        with patch.object(video_compress, "SCALING_OPTIONS", ((1, 4),)):
            self.assertEqual(source.calculate_scaling(1920, 1080), (1, 8))

    def test_wrapper_uses_pipeline_age_for_hysteresis(self):
        source = self.make_source(actual_scaling=(1, 2), last_pipeline_time=1024, get_video_fps=Mock(return_value=9))
        self.assertEqual(source.calculate_scaling(1920, 1080), (1, 2))
        source.last_pipeline_time = 1008
        self.assertEqual(source.calculate_scaling(1920, 1080), (1, 1))

    def test_fast_paths_do_not_measure_video(self):
        for changes, forced_scaling, expected in (
            ({}, (1, 2), (1, 2)),
            ({"scaling_control": 0}, None, (1, 1)),
            ({"scaling": (1, 2)}, None, (1, 2)),
            ({"statistics": SimpleNamespace(last_resized=1023.75, damage_events_count=100)}, None, (1, 2)),
            ({"last_scroll_time": 1020}, None, (1, 2)),
            ({"statistics": SimpleNamespace(last_resized=0, damage_events_count=50)}, None, (1, 1)),
            ({"content_types": ("text",)}, None, (1, 1)),
        ):
            with self.subTest(changes=changes, forced=forced_scaling), \
                    patch.object(video_compress, "SCALING_HARDCODED", forced_scaling):
                source = self.make_source(actual_scaling=(1, 2), **changes)
                self.assertEqual(source.calculate_scaling(1920, 1080), expected)
                source.get_video_fps.assert_not_called()
                source.matches_video_subregion.assert_not_called()
                source.subregion_is_video.assert_not_called()

    def test_zero_dimensions_do_not_need_window_state(self):
        source = WindowVideoSource.__new__(WindowVideoSource)
        self.assertEqual(source.calculate_scaling(0, 1080), (1, 1))
        self.assertEqual(source.calculate_scaling(1920, 0), (1, 1))

    def test_disabled_scaling_warns_once_when_required(self):
        source = WindowVideoSource.__new__(WindowVideoSource)
        with patch.object(video_compress, "SCALING", False), \
                patch.object(video_compress, "scalinglog") as log, \
                patch.object(video_compress, "first_time", side_effect=(True, False)) as first_time:
            self.assertEqual(source.calculate_scaling(1920, 1080), (1, 1))
            first_time.assert_not_called()
            for _ in range(2):
                self.assertEqual(source.calculate_scaling(8192, 2160), (1, 1))
            self.assertEqual(log.warn.call_count, 3)
            self.assertEqual(first_time.call_count, 2)


if __name__ == "__main__":
    unittest.main()
