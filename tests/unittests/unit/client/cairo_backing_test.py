#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest


class TestParsePaddingColors(unittest.TestCase):

    def test_empty_string(self):
        from xpra.cairo.backing_base import parse_padding_colors
        r = parse_padding_colors("")
        assert r == (0.0, 0.0, 0.0), f"expected black, got {r}"

    def test_valid_colors(self):
        from xpra.cairo.backing_base import parse_padding_colors
        r = parse_padding_colors("1.0,0.5,0.0")
        assert len(r) == 3
        assert abs(r[0] - 1.0) < 0.001
        assert abs(r[1] - 0.5) < 0.001
        assert abs(r[2] - 0.0) < 0.001

    def test_spaces_trimmed(self):
        from xpra.cairo.backing_base import parse_padding_colors
        r = parse_padding_colors(" 0.2 , 0.4 , 0.6 ")
        assert abs(r[0] - 0.2) < 0.001
        assert abs(r[1] - 0.4) < 0.001
        assert abs(r[2] - 0.6) < 0.001

    def test_too_few_components_falls_back_to_black(self):
        from xpra.cairo.backing_base import parse_padding_colors
        r = parse_padding_colors("0.5,0.5")
        assert r == (0.0, 0.0, 0.0)

    def test_non_numeric_falls_back_to_black(self):
        from xpra.cairo.backing_base import parse_padding_colors
        r = parse_padding_colors("red,green,blue")
        assert r == (0.0, 0.0, 0.0)


class TestClamp(unittest.TestCase):

    def test_below_zero(self):
        from xpra.cairo.backing_base import clamp
        assert clamp(-1.0) == 0.0
        assert clamp(-0.001) == 0.0

    def test_above_one(self):
        from xpra.cairo.backing_base import clamp
        assert clamp(1.001) == 1.0
        assert clamp(100.0) == 1.0

    def test_boundary_values(self):
        from xpra.cairo.backing_base import clamp
        assert clamp(0.0) == 0.0
        assert clamp(1.0) == 1.0

    def test_midrange(self):
        from xpra.cairo.backing_base import clamp
        assert clamp(0.5) == 0.5
        assert clamp(0.9999) == 0.9999


class TestGetScalingFilter(unittest.TestCase):

    def test_nearest_env_override(self):
        from xpra.cairo.backing_base import get_scaling_filter
        from xpra.util.env import OSEnvContext
        from cairo import FILTER_NEAREST
        with OSEnvContext(XPRA_SCALING_FILTER="nearest"):
            f = get_scaling_filter("text", 2.0, 2.0)
            assert f == FILTER_NEAREST

    def test_bilinear_env_override(self):
        from xpra.cairo.backing_base import get_scaling_filter
        from xpra.util.env import OSEnvContext
        from cairo import FILTER_GOOD
        with OSEnvContext(XPRA_SCALING_FILTER="bilinear"):
            f = get_scaling_filter("text", 2.0, 2.0)
            assert f == FILTER_GOOD

    def test_text_integer_upscale_uses_nearest(self):
        from xpra.cairo.backing_base import get_scaling_filter
        from xpra.util.env import OSEnvContext
        from cairo import FILTER_NEAREST
        with OSEnvContext(XPRA_SCALING_FILTER=""):
            f = get_scaling_filter("text", 2.0, 2.0)
            assert f == FILTER_NEAREST

    def test_text_non_integer_scale_uses_best(self):
        from xpra.cairo.backing_base import get_scaling_filter
        from xpra.util.env import OSEnvContext
        from cairo import FILTER_BEST
        with OSEnvContext(XPRA_SCALING_FILTER=""):
            f = get_scaling_filter("text", 1.5, 1.5)
            assert f == FILTER_BEST

    def test_non_text_uses_good(self):
        from xpra.cairo.backing_base import get_scaling_filter
        from xpra.util.env import OSEnvContext
        from cairo import FILTER_GOOD
        with OSEnvContext(XPRA_SCALING_FILTER=""):
            f = get_scaling_filter("video", 1.5, 1.5)
            assert f == FILTER_GOOD
            f = get_scaling_filter("", 2.0, 2.0)
            assert f == FILTER_GOOD


def main():
    unittest.main()


if __name__ == '__main__':
    main()
