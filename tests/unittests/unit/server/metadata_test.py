#!/usr/bin/env python3
# ABOUTME: Tests for the is_covered_by_opaque_region helper.
# ABOUTME: Verifies opaque-region coverage checks for various rectangle configurations.
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.common import is_covered_by_opaque_region


class TestIsCoveredByOpaqueRegion(unittest.TestCase):

    def test_empty_region(self):
        self.assertFalse(is_covered_by_opaque_region((), 1920, 1080))

    def test_single_rect_exact_match(self):
        # opaque region exactly matches window dimensions
        self.assertTrue(is_covered_by_opaque_region(((0, 0, 1920, 1080),), 1920, 1080))

    def test_single_rect_larger_than_window(self):
        # opaque region extends beyond window edges (still covers it)
        self.assertTrue(is_covered_by_opaque_region(((0, 0, 2000, 2000),), 1920, 1080))

    def test_single_rect_too_narrow(self):
        # opaque region doesn't cover full width
        self.assertFalse(is_covered_by_opaque_region(((0, 0, 960, 1080),), 1920, 1080))

    def test_single_rect_too_short(self):
        # opaque region doesn't cover full height
        self.assertFalse(is_covered_by_opaque_region(((0, 0, 1920, 540),), 1920, 1080))

    def test_single_rect_offset_from_origin(self):
        # opaque region starts away from origin, can't cover from (0,0)
        self.assertFalse(is_covered_by_opaque_region(((10, 10, 1920, 1080),), 1920, 1080))

    def test_negative_offset_covers_window(self):
        # opaque region starts before origin but is large enough to cover
        # (e.g. ox=-10, oy=-10, ow=1940, oh=1100 covers from 0,0 to 1920,1080)
        self.assertTrue(is_covered_by_opaque_region(((-10, -10, 1940, 1100),), 1920, 1080))

    def test_negative_offset_too_small(self):
        # starts before origin but not large enough to reach the far edge
        self.assertFalse(is_covered_by_opaque_region(((-10, -10, 1920, 1080),), 1920, 1080))

    def test_multiple_rects_one_covers(self):
        # second rect covers the full window; first doesn't
        self.assertTrue(is_covered_by_opaque_region(
            ((0, 0, 100, 100), (0, 0, 1920, 1080)),
            1920, 1080,
        ))

    def test_multiple_rects_none_covers(self):
        # no single rect covers the full window (even if combined they would)
        self.assertFalse(is_covered_by_opaque_region(
            ((0, 0, 960, 1080), (960, 0, 960, 1080)),
            1920, 1080,
        ))

    def test_zero_size_window(self):
        # degenerate: zero-size window is trivially covered
        self.assertTrue(is_covered_by_opaque_region(((0, 0, 0, 0),), 0, 0))


if __name__ == "__main__":
    unittest.main()
