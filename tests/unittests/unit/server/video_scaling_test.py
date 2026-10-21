#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# ABOUTME: Tests that verify_csc_and_encoder detects scaling changes.
# ABOUTME: Reproduces a bug where scaling=(1,2) was never recovered to (1,1).

import unittest

from xpra.util.objects import AdHocStruct
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


if __name__ == "__main__":
    unittest.main()
