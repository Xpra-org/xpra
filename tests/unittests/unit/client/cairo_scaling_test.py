#!/usr/bin/env python3
# ABOUTME: Tests for nearest-neighbor scaling filter selection in CairoBackingBase.
# ABOUTME: Verifies filter choice based on content type, scale factor, and env overrides.

# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

import cairo

from xpra.cairo.backing_base import get_scaling_filter


class ScalingFilterTest(unittest.TestCase):

    def test_text_integer_2x_uses_nearest(self):
        self.assertEqual(get_scaling_filter("text", 2.0, 2.0), cairo.FILTER_NEAREST)

    def test_text_integer_3x_uses_nearest(self):
        self.assertEqual(get_scaling_filter("text", 3.0, 3.0), cairo.FILTER_NEAREST)

    def test_text_non_integer_uses_best(self):
        self.assertEqual(get_scaling_filter("text", 1.5, 1.5), cairo.FILTER_BEST)

    def test_non_text_integer_2x_uses_good(self):
        self.assertEqual(get_scaling_filter("browser", 2.0, 2.0), cairo.FILTER_GOOD)

    def test_no_scaling_uses_best(self):
        self.assertEqual(get_scaling_filter("text", 1.0, 1.0), cairo.FILTER_BEST)

    def test_empty_content_type_uses_good(self):
        self.assertEqual(get_scaling_filter("", 2.0, 2.0), cairo.FILTER_GOOD)

    def test_asymmetric_integer_scale_uses_nearest(self):
        self.assertEqual(get_scaling_filter("text", 2.0, 3.0), cairo.FILTER_NEAREST)

    def test_asymmetric_mixed_scale_uses_best(self):
        self.assertEqual(get_scaling_filter("text", 2.0, 1.5), cairo.FILTER_BEST)

    def test_text_near_integer_2x_uses_nearest(self):
        """Pixel rounding can produce scale factors like 1.95 or 2.05."""
        self.assertEqual(get_scaling_filter("text", 1.95, 2.05), cairo.FILTER_NEAREST)

    def test_text_outside_tolerance_uses_best(self):
        """Text at non-integer scale uses Catmull-Rom (bicubic)."""
        self.assertEqual(get_scaling_filter("text", 2.2, 2.2), cairo.FILTER_BEST)

    def test_env_override_nearest(self):
        old = os.environ.get("XPRA_SCALING_FILTER")
        try:
            os.environ["XPRA_SCALING_FILTER"] = "nearest"
            self.assertEqual(get_scaling_filter("browser", 2.0, 2.0), cairo.FILTER_NEAREST)
        finally:
            if old is None:
                os.environ.pop("XPRA_SCALING_FILTER", None)
            else:
                os.environ["XPRA_SCALING_FILTER"] = old

    def test_env_override_bilinear(self):
        old = os.environ.get("XPRA_SCALING_FILTER")
        try:
            os.environ["XPRA_SCALING_FILTER"] = "bilinear"
            self.assertEqual(get_scaling_filter("text", 2.0, 2.0), cairo.FILTER_GOOD)
        finally:
            if old is None:
                os.environ.pop("XPRA_SCALING_FILTER", None)
            else:
                os.environ["XPRA_SCALING_FILTER"] = old

    def test_checkerboard_nearest_exact_pixel_doubling(self):
        """Paint a 2x2 checkerboard, scale 2x with NEAREST, verify exact pixel doubling."""
        # Create a 2x2 checkerboard: black/white/white/black
        src = cairo.ImageSurface(cairo.Format.ARGB32, 2, 2)
        ctx = cairo.Context(src)
        # pixel (0,0) = black
        ctx.set_source_rgb(0, 0, 0)
        ctx.rectangle(0, 0, 1, 1)
        ctx.fill()
        # pixel (1,0) = white
        ctx.set_source_rgb(1, 1, 1)
        ctx.rectangle(1, 0, 1, 1)
        ctx.fill()
        # pixel (0,1) = white
        ctx.set_source_rgb(1, 1, 1)
        ctx.rectangle(0, 1, 1, 1)
        ctx.fill()
        # pixel (1,1) = black
        ctx.set_source_rgb(0, 0, 0)
        ctx.rectangle(1, 1, 1, 1)
        ctx.fill()
        src.flush()

        # Scale 2x with NEAREST into a 4x4 surface
        dst = cairo.ImageSurface(cairo.Format.ARGB32, 4, 4)
        gc = cairo.Context(dst)
        gc.scale(2, 2)
        gc.set_source_surface(src, 0, 0)
        gc.get_source().set_filter(cairo.FILTER_NEAREST)
        gc.paint()
        dst.flush()

        # Read pixels — each source pixel should become an exact 2x2 block
        buf = dst.get_data()
        stride = dst.get_stride()

        def pixel_rgb(x, y):
            offset = y * stride + x * 4
            # ARGB32 is stored as native-endian uint32; on little-endian: B, G, R, A
            b, g, r = buf[offset], buf[offset + 1], buf[offset + 2]
            return (r, g, b)

        black = (0, 0, 0)
        white = (255, 255, 255)
        # Top-left 2x2 block should be black
        for dy in range(2):
            for dx in range(2):
                self.assertEqual(pixel_rgb(dx, dy), black,
                                 f"Expected black at ({dx},{dy})")
        # Top-right 2x2 block should be white
        for dy in range(2):
            for dx in range(2, 4):
                self.assertEqual(pixel_rgb(dx, dy), white,
                                 f"Expected white at ({dx},{dy})")
        # Bottom-left 2x2 block should be white
        for dy in range(2, 4):
            for dx in range(2):
                self.assertEqual(pixel_rgb(dx, dy), white,
                                 f"Expected white at ({dx},{dy})")
        # Bottom-right 2x2 block should be black
        for dy in range(2, 4):
            for dx in range(2, 4):
                self.assertEqual(pixel_rgb(dx, dy), black,
                                 f"Expected black at ({dx},{dy})")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
