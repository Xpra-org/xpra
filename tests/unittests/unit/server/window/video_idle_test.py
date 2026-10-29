#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock

from xpra.server.window.compress import WindowSource
from xpra.server.window.video_compress import WindowVideoSource

WIDTH = 2054
HEIGHT = 1112


class VideoIdleTest(unittest.TestCase):

    @staticmethod
    def make_video_source(encoder_closed=False) -> WindowVideoSource:
        source = object.__new__(WindowVideoSource)
        source.non_video_encodings = ("jpeg", "png")
        source.common_video_encodings = ("h264", )
        source.supports_scrolling = False
        source.is_tray = False
        source.is_shadow = False
        source.content_types = ("video", )
        source.width_mask = 0xFFFE
        source.height_mask = 0xFFFE
        source.encoding = "auto"
        source.pixel_format = ""
        source._rgb_auto_threshold = 16384
        source.video_subregion = SimpleNamespace(rectangle=None)
        source.min_w = source.min_h = 16
        source.max_w = source.max_h = 4096
        source._fixed_min_quality = 0
        source._fixed_max_quality = 100
        source._current_quality = 50
        source._video_encoder = Mock(is_closed=Mock(return_value=encoder_closed))
        source.last_pipeline_params = (("h264", ), WIDTH, HEIGHT, "BGRX")
        source.verify_csc_and_encoder = Mock(return_value=True)
        now = monotonic()
        source.statistics = SimpleNamespace(last_packet_time=now-1.5, last_resized=now-60)
        return source

    def get_best_encoding(self, source: WindowVideoSource, width=WIDTH, height=HEIGHT) -> str:
        nonvideo = Mock(return_value="jpeg")
        original = WindowSource.get_auto_encoding
        WindowSource.get_auto_encoding = nonvideo
        try:
            return source.get_best_encoding_video(width, height, {}, "auto")
        finally:
            WindowSource.get_auto_encoding = original

    def test_slow_updates_keep_using_the_current_video_pipeline(self) -> None:
        source = self.make_video_source()
        self.assertEqual(self.get_best_encoding(source), "auto")

    def test_slow_updates_without_a_video_encoder_use_nonvideo(self) -> None:
        source = self.make_video_source()
        source._video_encoder = None
        self.assertEqual(self.get_best_encoding(source), "jpeg")

    def test_slow_updates_with_a_closed_video_encoder_use_nonvideo(self) -> None:
        source = self.make_video_source(encoder_closed=True)
        self.assertEqual(self.get_best_encoding(source), "jpeg")

    def test_slow_updates_for_a_different_area_use_nonvideo(self) -> None:
        source = self.make_video_source()
        self.assertEqual(self.get_best_encoding(source, 640, 480), "jpeg")

    def test_slow_updates_with_an_outdated_pipeline_use_nonvideo(self) -> None:
        source = self.make_video_source()
        source.verify_csc_and_encoder.return_value = False
        self.assertEqual(self.get_best_encoding(source), "jpeg")

    def test_video_pipeline_ready_requires_scored_dimensions(self) -> None:
        source = self.make_video_source()
        source.last_pipeline_params = ()
        self.assertFalse(source.video_pipeline_ready(WIDTH, HEIGHT))
        source.last_pipeline_params = (("h264", ), WIDTH, HEIGHT, "BGRX")
        self.assertTrue(source.video_pipeline_ready(WIDTH, HEIGHT))
        self.assertFalse(source.video_pipeline_ready(WIDTH, HEIGHT - 2))


if __name__ == "__main__":
    unittest.main()
