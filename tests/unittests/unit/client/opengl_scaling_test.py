#!/usr/bin/env python3
# ABOUTME: Tests for Catmull-Rom bicubic scaling in the OpenGL renderer.
# ABOUTME: Verifies shader registration, weight math, 2D interpolation, and env var logic.

# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import math
import unittest


def catmull_rom_weights(t):
    """Compute the 4 Catmull-Rom weights for fractional position t in [0,1)."""
    w0 = t * (-0.5 + t * (1.0 - 0.5 * t))
    w1 = 1.0 + t * t * (-2.5 + 1.5 * t)
    w2 = t * (0.5 + t * (2.0 - 1.5 * t))
    w3 = t * t * (-0.5 + 0.5 * t)
    return w0, w1, w2, w3


def catmull_rom_2d(grid, x, y):
    """
    2D Catmull-Rom interpolation on a grid using the 9-tap bilinear trick.
    grid is a 2D list/array indexed as grid[row][col].
    x, y are floating-point coordinates (column, row).
    """
    rows = len(grid)
    cols = len(grid[0])

    # Texel center nearest to coord
    cx = math.floor(x - 0.5) + 0.5
    cy = math.floor(y - 0.5) + 0.5
    fx = x - cx
    fy = y - cy

    wx = catmull_rom_weights(fx)
    wy = catmull_rom_weights(fy)

    # Merge middle pair for bilinear trick
    w12x = wx[1] + wx[2]
    w12y = wy[1] + wy[2]
    offset12x = wx[2] / w12x if w12x != 0 else 0
    offset12y = wy[2] / w12y if w12y != 0 else 0

    # Sample positions
    p0x = cx - 1.0
    p12x = cx + offset12x
    p3x = cx + 2.0
    p0y = cy - 1.0
    p12y = cy + offset12y
    p3y = cy + 2.0

    def sample(sx, sy):
        """Bilinear sample at (sx, sy) with clamp-to-edge."""
        # Integer part and fraction
        ix = math.floor(sx - 0.5)
        iy = math.floor(sy - 0.5)
        fxx = sx - (ix + 0.5)
        fyy = sy - (iy + 0.5)

        def clamp_get(r, c):
            r = max(0, min(rows - 1, r))
            c = max(0, min(cols - 1, c))
            return grid[r][c]

        # Bilinear interpolation
        v00 = clamp_get(iy, ix)
        v10 = clamp_get(iy, ix + 1)
        v01 = clamp_get(iy + 1, ix)
        v11 = clamp_get(iy + 1, ix + 1)
        top = v00 * (1 - fxx) + v10 * fxx
        bot = v01 * (1 - fxx) + v11 * fxx
        return top * (1 - fyy) + bot * fyy

    xs = [p0x, p12x, p3x]
    ys = [p0y, p12y, p3y]
    wxs = [wx[0], w12x, wx[3]]
    wys = [wy[0], w12y, wy[3]]

    result = 0.0
    for j, (sy, wy_val) in enumerate(zip(ys, wys)):
        for i, (sx, wx_val) in enumerate(zip(xs, wxs)):
            result += sample(sx, sy) * wx_val * wy_val
    return result


# --- Shader registration tests ---

class UpscaleShaderRegistrationTest(unittest.TestCase):

    def test_upscale_shader_in_source_dict(self):
        from xpra.opengl.shaders import SOURCE
        self.assertIn("upscale", SOURCE)

    def test_upscale_shader_has_required_uniforms(self):
        from xpra.opengl.shaders import SOURCE
        source = SOURCE["upscale"]
        self.assertIn("uniform sampler2DRect fbo", source)
        self.assertIn("uniform vec2 viewport_pos", source)
        self.assertIn("uniform vec2 scaling", source)

    def test_upscale_shader_has_catmull_rom_function(self):
        from xpra.opengl.shaders import SOURCE
        source = SOURCE["upscale"]
        self.assertIn("textureCatmullRom", source)

    def test_upscale_shader_version_330(self):
        from xpra.opengl.shaders import SOURCE
        source = SOURCE["upscale"]
        self.assertIn("#version 330 core", source)


# --- Catmull-Rom weight math tests ---

class CatmullRomWeightTest(unittest.TestCase):

    def test_cr_weights_sum_to_one(self):
        """Partition of unity: weights sum to 1.0 for any t in [0,1)."""
        for i in range(100):
            t = i / 100.0
            w0, w1, w2, w3 = catmull_rom_weights(t)
            self.assertAlmostEqual(w0 + w1 + w2 + w3, 1.0, places=12,
                                   msg=f"Weights don't sum to 1 at t={t}")

    def test_cr_weights_at_integer_position(self):
        """At t=0, weights should be (0, 1, 0, 0) — passes through center."""
        w0, w1, w2, w3 = catmull_rom_weights(0.0)
        self.assertAlmostEqual(w0, 0.0)
        self.assertAlmostEqual(w1, 1.0)
        self.assertAlmostEqual(w2, 0.0)
        self.assertAlmostEqual(w3, 0.0)

    def test_cr_weights_at_midpoint(self):
        """At t=0.5, known Catmull-Rom values: (-1/16, 9/16, 9/16, -1/16)."""
        w0, w1, w2, w3 = catmull_rom_weights(0.5)
        self.assertAlmostEqual(w0, -1 / 16)
        self.assertAlmostEqual(w1, 9 / 16)
        self.assertAlmostEqual(w2, 9 / 16)
        self.assertAlmostEqual(w3, -1 / 16)

    def test_cr_outer_weights_negative(self):
        """w0 and w3 are negative for t in (0,1) — why 4-fetch bilinear trick fails."""
        for i in range(1, 100):
            t = i / 100.0
            w0, _, _, w3 = catmull_rom_weights(t)
            self.assertLess(w0, 0, f"w0 should be negative at t={t}")
            self.assertLess(w3, 0, f"w3 should be negative at t={t}")

    def test_cr_middle_pair_positive(self):
        """w1+w2 should be positive for all t — why 9-tap works."""
        for i in range(100):
            t = i / 100.0
            _, w1, w2, _ = catmull_rom_weights(t)
            self.assertGreater(w1 + w2, 0, f"w1+w2 should be positive at t={t}")


# --- Bilinear trick validation tests ---

class BilinearTrickTest(unittest.TestCase):

    def test_center_offset_in_valid_range(self):
        """w2/(w1+w2) must be in [0,1] for the bilinear trick to work on the center pair."""
        for i in range(100):
            t = i / 100.0
            _, w1, w2, _ = catmull_rom_weights(t)
            w12 = w1 + w2
            if w12 == 0:
                continue
            offset = w2 / w12
            self.assertGreaterEqual(offset, 0.0, f"Offset out of range at t={t}")
            self.assertLessEqual(offset, 1.0, f"Offset out of range at t={t}")

    def test_corner_weights_cannot_merge(self):
        """w0/(w0+w1) goes outside [0,1] — confirms 4-tap approach is invalid."""
        out_of_range = False
        for i in range(1, 100):
            t = i / 100.0
            w0, w1, _, _ = catmull_rom_weights(t)
            denom = w0 + w1
            if denom == 0:
                continue
            offset = w0 / denom
            if offset < 0 or offset > 1:
                out_of_range = True
                break
        self.assertTrue(out_of_range,
                        "Expected w0/(w0+w1) to go outside [0,1] for some t")


# --- 2D interpolation correctness tests ---

class CatmullRom2DTest(unittest.TestCase):

    def test_cr_2d_passes_through_grid_points(self):
        """Sampling at integer coords returns the grid value exactly."""
        grid = [
            [1.0, 2.0, 3.0, 4.0],
            [5.0, 6.0, 7.0, 8.0],
            [9.0, 10.0, 11.0, 12.0],
            [13.0, 14.0, 15.0, 16.0],
        ]
        for r in range(4):
            for c in range(4):
                # Sample at texel center (col + 0.5, row + 0.5)
                val = catmull_rom_2d(grid, c + 0.5, r + 0.5)
                self.assertAlmostEqual(val, grid[r][c], places=6,
                                       msg=f"Grid passthrough failed at ({c},{r})")

    def test_cr_2d_symmetric(self):
        """On a uniform grid, sampling at midpoints returns the grid value."""
        grid = [[5.0] * 6 for _ in range(6)]
        val = catmull_rom_2d(grid, 3.0, 3.0)
        self.assertAlmostEqual(val, 5.0, places=6)

    def test_cr_2d_sharper_than_bilinear(self):
        """For a step edge, CR produces values closer to 0 or 1 than bilinear."""
        # Step edge: left half = 0, right half = 1
        grid = [[0.0, 0.0, 0.0, 1.0, 1.0, 1.0] for _ in range(6)]
        # Sample just right of the edge
        x = 3.25
        y = 3.0
        cr_val = catmull_rom_2d(grid, x, y)
        # Bilinear at same position: linear interpolation between 0 and 1
        bilinear_val = 0.25  # fraction past edge
        # CR should overshoot slightly past 0.25 (sharper transition)
        # The exact value depends on weights, but CR with negative lobes
        # produces values closer to 1.0 than bilinear for this sample point
        self.assertGreater(cr_val, bilinear_val,
                           "CR should be sharper (closer to 1) than bilinear near step edge")


# --- Env var logic tests ---

class OpenGLScalingFilterEnvTest(unittest.TestCase):
    """Tests for the XPRA_OPENGL_SCALING_FILTER env var logic."""

    def _should_use_catmull_rom(self, scaling, programs_has_upscale, env_value=""):
        """
        Reproduce the decision logic from do_present_fbo():
        Use CR when: scaling AND env not overridden AND "upscale" in programs.
        """
        programs = {"upscale": 1} if programs_has_upscale else {}
        filter_env = env_value.lower()
        return (scaling
                and filter_env not in ("bilinear", "nearest")
                and "upscale" in programs)

    def test_default_uses_catmull_rom(self):
        self.assertTrue(self._should_use_catmull_rom(
            scaling=True, programs_has_upscale=True, env_value=""))

    def test_env_bilinear_disables_cr(self):
        self.assertFalse(self._should_use_catmull_rom(
            scaling=True, programs_has_upscale=True, env_value="bilinear"))

    def test_env_nearest_disables_cr(self):
        self.assertFalse(self._should_use_catmull_rom(
            scaling=True, programs_has_upscale=True, env_value="nearest"))

    def test_no_shader_falls_back(self):
        self.assertFalse(self._should_use_catmull_rom(
            scaling=True, programs_has_upscale=False, env_value=""))

    def test_integer_scale_no_cr(self):
        """At integer scales, scaling=False, CR not used."""
        self.assertFalse(self._should_use_catmull_rom(
            scaling=False, programs_has_upscale=True, env_value=""))

    def test_1x_no_cr(self):
        """At 1:1 scale, scaling=False, CR not used."""
        self.assertFalse(self._should_use_catmull_rom(
            scaling=False, programs_has_upscale=True, env_value=""))


def main():
    unittest.main()


if __name__ == '__main__':
    main()
