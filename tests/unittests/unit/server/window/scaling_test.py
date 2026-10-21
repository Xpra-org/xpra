#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from dataclasses import replace

from xpra.server.window.scaling import (
    ScalingSettings, ScalingState, calculate_scaling, get_min_required_scaling, get_scaling_override,
)


class ScalingPolicyTest(unittest.TestCase):
    state = ScalingState(1920, 1080, quality=40, speed=50, damage_events_count=100, content_types=("video",))
    settings = ScalingSettings()

    def test_minimum_required_by_codec(self):
        for width, height, max_width, max_height, expected in (
            (4096, 4096, 4096, 4096, (1, 1)),
            (6144, 2160, 4096, 4096, (2, 3)),
            (8192, 4096, 4096, 4096, (1, 2)),
            (1000, 4000, 4096, 2048, (1, 2)),
            (16384, 8192, 4096, 4096, (1, 4)),
        ):
            with self.subTest(size=(width, height), maximum=(max_width, max_height)):
                state = replace(self.state, width=width, height=height, max_width=max_width, max_height=max_height)
                self.assertEqual(get_min_required_scaling(state, self.settings), expected)

    def test_minimum_required_by_client(self):
        state = replace(self.state, client_render_size=(1280, 720))
        self.assertEqual(get_min_required_scaling(state, self.settings), (2, 3))
        self.assertEqual(get_min_required_scaling(state, replace(self.settings, downscale=False)), (1, 1))
        # A larger client render area must not relax the codec's own limits.
        state = replace(state, max_width=1024, client_render_size=(3840, 2160))
        self.assertEqual(get_min_required_scaling(state, self.settings), (1, 2))

    def test_minimum_retains_default_when_size_fits(self):
        self.assertEqual(get_min_required_scaling(self.state, self.settings, (1, 3)), (1, 3))
        state = replace(self.state, width=8192)
        # When the size does not fit, existing behavior selects the largest fit.
        self.assertEqual(get_min_required_scaling(state, self.settings, (1, 3)), (1, 2))

    def test_option_order_and_equivalent_ratios(self):
        state = replace(self.state, max_width=1024)
        settings = replace(self.settings, options=((1, 2), (1, 1), (1, 4), (2, 4)))
        self.assertEqual(get_min_required_scaling(state, settings), (2, 4))

    def test_no_ratio_fits(self):
        state = replace(self.state, width=100000)
        with self.assertRaisesRegex(ValueError, "failed to find a scaling value for window size 100000x1080"):
            get_min_required_scaling(state, self.settings)

    def test_zero_dimensions_and_disabled_scaling(self):
        settings = replace(self.settings, forced_scaling=(1, 2))
        for width, height in ((0, 1080), (1920, 0), (0, 0)):
            with self.subTest(size=(width, height)):
                self.assertEqual(calculate_scaling(replace(self.state, width=width, height=height), settings), (1, 1))
        state = replace(self.state, width=8192)
        self.assertEqual(calculate_scaling(state, replace(settings, enabled=False)), (1, 1))

    def test_explicit_controls_and_precedence(self):
        for state_changes, settings_changes, expected in (
            ({"control": 0}, {"forced_scaling": (1, 2)}, (1, 2)),
            ({"control": 0, "requested_scaling": (1, 3)}, {}, (1, 1)),
            ({"control": 0, "width": 8192}, {}, (1, 2)),
            ({"requested_scaling": (1, 2), "time_since_resize": 0}, {}, (1, 2)),
            ({"requested_scaling": (1, 20)}, {}, (1, 20)),
            ({}, {"forced_scaling": (1, 20)}, (1, 20)),
            ({"width": 8192, "requested_scaling": (1, 3)}, {}, (1, 2)),
        ):
            with self.subTest(state=state_changes, settings=settings_changes):
                self.assertEqual(calculate_scaling(replace(self.state, **state_changes),
                                                   replace(self.settings, **settings_changes), fps=60), expected)

    def test_holdoff_boundaries_and_sample_count(self):
        for changes, expected in (
            ({"time_since_resize": 0.499}, (1, 2)),
            ({"time_since_resize": 0.5}, None),
            ({"time_since_scroll": 4.999}, (1, 2)),
            ({"time_since_scroll": 5}, None),
            ({"damage_events_count": 50}, (1, 1)),
            ({"damage_events_count": 51}, None),
            ({"time_since_resize": 0, "width": 16384}, (1, 4)),
        ):
            with self.subTest(changes=changes):
                state = replace(self.state, actual_scaling=(1, 2), **changes)
                self.assertEqual(get_scaling_override(state, self.settings), expected)

    def test_text_holdoff(self):
        state = replace(self.state, content_types=("text",))
        self.assertEqual(calculate_scaling(state, self.settings, fps=60), (1, 1))
        self.assertIsNone(get_scaling_override(state, replace(self.settings, text_quality=90)))
        self.assertEqual(calculate_scaling(state, replace(self.settings, text_quality=90), fps=60), (2, 3))

    def test_automatic_quality_and_speed(self):
        # These expected decisions were captured from the original window-source method.
        for changes, fps, expected in (
            ({}, 60, (1, 3)),
            ({"quality": 94}, 60, (1, 2)),
            ({"quality": 95}, 60, (1, 1)),
            ({"content_types": (), "quality": 64}, 60, (2, 3)),
            ({"content_types": (), "quality": 65}, 60, (1, 1)),
            ({"speed": 100}, 60, (1, 5)),
            ({"speed": 0}, 60, (1, 1)),
            ({}, 0, (1, 1)),
            ({"quality": 100, "max_width": 1024}, 60, (1, 2)),
        ):
            with self.subTest(changes=changes, fps=fps):
                self.assertEqual(calculate_scaling(replace(self.state, **changes), self.settings, fps=fps), expected)

    def test_bandwidth_and_content(self):
        for changes, expected in (
            ({"bandwidth_limit": 7}, (1, 10)),
            ({"bandwidth_limit": 1000000}, (1, 10)),
            ({"bandwidth_limit": 10000000}, (1, 5)),
            ({"is_shadow": True}, (1, 1)),
            ({"image_depth": 30}, (1, 1)),
            ({"content_types": ()}, (1, 2)),
        ):
            with self.subTest(changes=changes):
                self.assertEqual(calculate_scaling(replace(self.state, **changes), self.settings, fps=60), expected)

    def test_video_subregion_classification(self):
        state = replace(self.state, content_types=())
        for matches, video, expected in ((True, True, (1, 3)), (True, False, (1, 2)), (False, True, (1, 2))):
            with self.subTest(matches=matches, video=video):
                self.assertEqual(calculate_scaling(state, self.settings, fps=60,
                                                   matches_subregion=matches, subregion_is_video=video), expected)

    def test_client_scaling_and_thresholds(self):
        for render_size, expected in (((960, 540), (1, 4)), ((1280, 720), (1, 3)), ((1280, 500), (1, 4.32))):
            with self.subTest(render_size=render_size):
                state = replace(self.state, client_render_size=render_size)
                result = calculate_scaling(state, self.settings, fps=60)
                self.assertEqual(result[0], expected[0])
                self.assertAlmostEqual(result[1], expected[1])
                self.assertEqual(calculate_scaling(state, replace(self.settings, downscale=False), fps=60), (1, 3))
        state = replace(self.state, client_render_size=(1900, 1060))
        self.assertEqual(calculate_scaling(state, self.settings, fps=60), (1, 3))
        result = calculate_scaling(state, replace(self.settings, downscale_threshold=0), fps=60)
        self.assertEqual(result[0], 1)
        self.assertAlmostEqual(result[1], 3.0566037735849054)

    def test_pipeline_hysteresis(self):
        state = replace(self.state, actual_scaling=(1, 2))
        for age, expected in ((-1, (1, 2)), (0, (1, 2)), (16, (1, 1)), (1000, (1, 1))):
            with self.subTest(age=age):
                self.assertEqual(calculate_scaling(replace(state, time_since_pipeline=age), self.settings, fps=9), expected)

    def test_manual_controls(self):
        for changes, fps, expected in (
            ({"control": 50, "fullscreen": True}, 60, (1, 3)),
            ({"control": 50, "maximized": True}, 60, (1, 2)),
            ({"control": 50, "width": 3840, "height": 2160}, 60, (1, 3)),
            ({"control": 100}, 60, (2, 3)),
            ({"control": 100, "width": 1280, "height": 1024}, 60, (2, 3)),
            ({"control": 100, "width": 640, "height": 480}, 60, (1, 1)),
            ({"control": 100, "fullscreen": True, "quality": 100, "speed": 0}, 1, (1, 1)),
            ({"control": 100, "fullscreen": True, "speed": 100}, 0, (1, 3)),
            ({"control": 100, "actual_scaling": (1, 3)}, 60, (1, 3)),
        ):
            with self.subTest(changes=changes, fps=fps):
                self.assertEqual(calculate_scaling(replace(self.state, **changes), self.settings, fps=fps), expected)

    def test_manual_subregion_aggressiveness(self):
        state = replace(self.state, control=25, width=1280, height=720, content_types=())
        self.assertEqual(calculate_scaling(state, self.settings, fps=60, matches_subregion=True, subregion_is_video=True), (1, 3))
        self.assertEqual(calculate_scaling(state, self.settings, fps=60, matches_subregion=True), (1, 1))

    def test_automatic_ratio_bounds_and_no_candidates(self):
        for options, expected in ((((2, 1),), (1, 1)), (((1, 20),), (1, 10)), ((), (1, 1))):
            with self.subTest(options=options):
                self.assertEqual(calculate_scaling(self.state, replace(self.settings, options=options), fps=60), expected)


if __name__ == '__main__':
    unittest.main()
