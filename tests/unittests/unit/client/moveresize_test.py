#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# ABOUTME: Tests for resize increment snapping in manual moveresize.
# ABOUTME: Verifies that alt-drag resize respects size hint increments (eg terminal cells).

import unittest

from xpra.client.gtk3.window.base import snap_to_increment


class TestSnapToIncrement(unittest.TestCase):

    def test_no_increment(self):
        # no increment hints: size unchanged
        assert snap_to_increment(803, 605, {}) == (803, 605)

    def test_increment_of_one(self):
        # increment of 1 is effectively no snapping
        hints = {"width_inc": 1, "height_inc": 1}
        assert snap_to_increment(803, 605, hints) == (803, 605)

    def test_snap_width_only(self):
        # xterm-like: 10px wide cells, 4px base (scrollbar/border)
        hints = {"width_inc": 10, "height_inc": 1, "base_width": 4, "base_height": 0}
        # 803 -> 4 + 79*10 = 794 (floor to grid)
        assert snap_to_increment(803, 605, hints) == (794, 605)

    def test_snap_height_only(self):
        hints = {"width_inc": 1, "height_inc": 20, "base_width": 0, "base_height": 2}
        # 605 -> 2 + 30*20 = 602
        assert snap_to_increment(400, 605, hints) == (400, 602)

    def test_snap_both(self):
        # typical terminal: 10x20 cells, 4x2 base
        hints = {"width_inc": 10, "height_inc": 20, "base_width": 4, "base_height": 2}
        assert snap_to_increment(803, 605, hints) == (794, 602)

    def test_exact_grid_unchanged(self):
        hints = {"width_inc": 10, "height_inc": 20, "base_width": 4, "base_height": 2}
        # 4 + 80*10 = 804, 2 + 30*20 = 602 — already on grid
        assert snap_to_increment(804, 602, hints) == (804, 602)

    def test_base_size_defaults_to_zero(self):
        hints = {"width_inc": 10, "height_inc": 20}
        # no base_width/base_height → defaults to 0
        # 803 -> 0 + 80*10 = 800
        # 605 -> 0 + 30*20 = 600
        assert snap_to_increment(803, 605, hints) == (800, 600)

    def test_size_smaller_than_base(self):
        hints = {"width_inc": 10, "height_inc": 20, "base_width": 50, "base_height": 40}
        # size below base: unchanged (remainder is 0)
        assert snap_to_increment(30, 20, hints) == (30, 20)

    def test_one_increment_above_base(self):
        hints = {"width_inc": 10, "height_inc": 20, "base_width": 4, "base_height": 2}
        # 14 = 4 + 1*10, 22 = 2 + 1*20
        assert snap_to_increment(14, 22, hints) == (14, 22)
        # just shy of next increment
        assert snap_to_increment(23, 41, hints) == (14, 22)

    def test_server_coord_snap_at_noninteger_scale(self):
        # At 1.6x scale: server base=4, inc=10. geometry_hints would drop base_width
        # (4*1.6=6.4 is not integer) but keep width_inc (10*1.6=16 is integer).
        # Snapping in server coordinates with the full server hints gives correct result.
        # Client 810 -> cx=round(810/1.6)=506 -> snap -> sx=round(*1.6)=client
        hints = {"width_inc": 10, "height_inc": 10, "base_width": 4, "base_height": 4}
        sw, sh = snap_to_increment(round(810 / 1.6), round(610 / 1.6), hints)
        assert sw == 504  # 4 + 50*10
        assert sh == 374  # 4 + 37*10
        # converting back: sx(504)=round(504*1.6)=806, sx(374)=round(374*1.6)=598
        assert round(sw * 1.6) == 806
        assert round(sh * 1.6) == 598

    def test_server_coord_snap_integer_scale(self):
        # At 2x scale: server base=4, inc=10 -> client base=8, inc=20 (both scale exactly).
        # Snapping in server coords must give same result as snapping in client coords.
        hints = {"width_inc": 10, "height_inc": 10, "base_width": 4, "base_height": 4}
        sw, sh = snap_to_increment(round(810 / 2), round(610 / 2), hints)
        assert sw == 404  # 4 + 40*10
        assert sh == 304  # 4 + 30*10
        # converting back: sx=round(*2)=808 and 608
        assert round(sw * 2) == 808
        assert round(sh * 2) == 608

    def test_nearest_rounds_to_closest(self):
        hints = {"width_inc": 10, "height_inc": 10, "base_width": 4, "base_height": 4}
        # 810 is 6 past 804, closer to 814 → rounds up
        assert snap_to_increment(810, 810, hints, nearest=True) == (814, 814)
        # 808 is 4 past 804, closer to 804 → rounds down
        assert snap_to_increment(808, 808, hints, nearest=True) == (804, 804)
        # 809 is exactly 5 past 804 (midpoint) → rounds up
        assert snap_to_increment(809, 809, hints, nearest=True) == (814, 814)
        # already on grid
        assert snap_to_increment(804, 804, hints, nearest=True) == (804, 804)

    def test_nearest_stable_roundtrip_sub1x_scale(self):
        # At 0.5x scale: the cx→snap_nearest→sx round-trip must be a fixed point.
        # This is the key property that prevents oscillation at sub-1x scales.
        hints = {"width_inc": 7, "height_inc": 7, "base_width": 4, "base_height": 4}
        scale = 0.5
        for client_w in range(20, 40):
            server_w = round(client_w / scale)
            snapped_sw = snap_to_increment(server_w, server_w, hints, nearest=True)[0]
            snapped_cw = round(snapped_sw * scale)
            # round-trip from snapped client value must be stable
            server_w2 = round(snapped_cw / scale)
            snapped_sw2 = snap_to_increment(server_w2, server_w2, hints, nearest=True)[0]
            snapped_cw2 = round(snapped_sw2 * scale)
            assert snapped_cw == snapped_cw2, \
                f"unstable at client_w={client_w}: {snapped_cw} → {snapped_cw2}"

    def test_snap_shrinks_maximized_size(self):
        # Snapping a maximized/fullscreen window would shrink it below screen size.
        # This validates WHY we skip snapping for maximized/fullscreen windows.
        hints = {"width_inc": 10, "height_inc": 20, "base_width": 4, "base_height": 2}
        screen_w, screen_h = 1920, 1080
        snapped_w, snapped_h = snap_to_increment(screen_w, screen_h, hints)
        # screen size is almost never on the grid — snap shrinks it
        assert snapped_w <= screen_w
        assert snapped_h <= screen_h
        assert (snapped_w, snapped_h) != (screen_w, screen_h)


if __name__ == "__main__":
    unittest.main()
