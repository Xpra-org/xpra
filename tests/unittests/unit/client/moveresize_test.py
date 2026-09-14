#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# ABOUTME: Tests for resize increment snapping in manual moveresize.
# ABOUTME: Verifies that alt-drag resize respects size hint increments (eg terminal cells).

import os
import unittest

from xpra.os_util import gi_import
from xpra.constants import MoveResize
from xpra.client.gtk3.window.base import calculate_moveresize_data, snap_to_increment


class TestCalculateMoveResizeData(unittest.TestCase):

    def test_directions(self):
        expected = {
            MoveResize.MOVE: ((17, 29), ()),
            MoveResize.SIZE_BOTTOMRIGHT: ((), (107, 89)),
            MoveResize.SIZE_BOTTOM: ((), (100, 89)),
            MoveResize.SIZE_BOTTOMLEFT: ((17, 20), (93, 89)),
            MoveResize.SIZE_RIGHT: ((), (107, 80)),
            MoveResize.SIZE_LEFT: ((17, 20), (93, 80)),
            MoveResize.SIZE_TOPRIGHT: ((10, 29), (107, 71)),
            MoveResize.SIZE_TOP: ((10, 29), (100, 71)),
            MoveResize.SIZE_TOPLEFT: ((17, 29), (93, 71)),
        }
        for direction, data in expected.items():
            with self.subTest(direction=direction):
                assert calculate_moveresize_data(direction, 10, 20, 100, 80,
                                                 7, 9, 1, 1, 500, 500) == (data, 7, 9)

    def test_clamping(self):
        assert calculate_moveresize_data(MoveResize.SIZE_BOTTOM, 10, 20, 100, 80,
                                         7, -100, 70, 50, 120, 90) == (((), (100, 50)), 7, -30)
        assert calculate_moveresize_data(MoveResize.SIZE_TOP, 10, 20, 100, 80,
                                         7, 100, 70, 50, 120, 90) == (((10, 50), (100, 50)), 7, 30)
        assert calculate_moveresize_data(MoveResize.SIZE_RIGHT, 10, 20, 100, 80,
                                         -100, 9, 70, 50, 120, 90) == (((), (70, 80)), -30, 9)
        assert calculate_moveresize_data(MoveResize.SIZE_LEFT, 10, 20, 100, 80,
                                         -100, 9, 70, 50, 120, 90) == (((-10, 20), (120, 80)), -20, 9)

    def test_unhandled_direction(self):
        assert calculate_moveresize_data(MoveResize.CANCEL, 10, 20, 100, 80,
                                         7, 9, 1, 1, 500, 500) == ((), 7, 9)


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


class TestMoveResizeCursor(unittest.TestCase):
    """
    Whilst we drag the window ourselves, the cursor belongs to the drag
    and not to the remote application.
    On the platforms where the drag is done with a pointer grab
    (x11, win32, wayland), the grab's cursor wins and this is a no-op,
    but macos has no grab - and neither does our own fallback drag.
    """

    @classmethod
    def setUpClass(cls):
        if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            raise unittest.SkipTest("no display")

    def make_window(self):
        """ the smallest object the moveresize cursor methods need """
        from xpra.client.gtk3.window.base import GTKClientWindowBase
        from xpra.client.gtk3.window.pointer import PointerWindow
        Gtk = gi_import("Gtk")

        applied = []

        class FakeClient:
            @staticmethod
            def set_windows_cursor(windows, cursor_data) -> None:
                applied.append((tuple(windows), cursor_data))

        class FakeWindow:
            set_moveresize_cursor = GTKClientWindowBase.set_moveresize_cursor
            cancel_moveresize_cursor = GTKClientWindowBase.cancel_moveresize_cursor
            key_may_break_moveresize = GTKClientWindowBase.key_may_break_moveresize
            focus_may_break_moveresize = GTKClientWindowBase.focus_may_break_moveresize
            do_poll_buttons = PointerWindow.do_poll_buttons

            def __init__(self):
                self.moveresize_cursor = ""
                self.moveresize_event = ()
                self.cursor_data = ()
                self.button_pressed: dict[int, int] = {}
                self._client = FakeClient()
                self.toplevel = Gtk.Window()
                self.drawing_area = Gtk.DrawingArea()
                self.toplevel.add(self.drawing_area)
                self.toplevel.realize()
                # the drawing area needs its own gdk window,
                # that is the one the cursor gets set on:
                self.drawing_area.show()
                self.drawing_area.realize()
                assert self.drawing_area.get_window()

            @staticmethod
            def get_subsystem(_name):
                return None

        return FakeWindow(), applied

    def test_direction_sets_the_matching_cursor(self):
        from xpra.client.gtk3.window.base import MOVERESIZE_CURSOR_MAP
        from xpra.gtk.cursors import new_cursor
        window, _ = self.make_window()
        gdkwin = window.drawing_area.get_window()
        display = gdkwin.get_display()
        expected = {
            MoveResize.SIZE_TOPLEFT: "nw-resize",
            MoveResize.SIZE_BOTTOMRIGHT: "se-resize",
            MoveResize.SIZE_LEFT: "w-resize",
            MoveResize.MOVE: "move",
        }
        for direction, name in expected.items():
            with self.subTest(direction=direction):
                assert MOVERESIZE_CURSOR_MAP.get(direction) == name
                # the name must resolve to a real cursor, or we would set nothing:
                assert new_cursor(display, name), f"no cursor for {name!r}"
                window.set_moveresize_cursor(direction)
                assert window.moveresize_cursor == name

    def test_cancel_restores_the_server_cursor(self):
        window, applied = self.make_window()
        window.cursor_data = ("raw", 0, 0, 16, 16, 0, 0, 0x1234, b"\xff" * 1024, "left_ptr")
        window.set_moveresize_cursor(MoveResize.SIZE_BOTTOMRIGHT)
        assert not applied, "nothing should have been re-applied yet"
        window.cancel_moveresize_cursor()
        assert window.moveresize_cursor == ""
        assert applied == [((window, ), window.cursor_data)], f"{applied=}"
        # a second cancel is a no-op:
        window.cancel_moveresize_cursor()
        assert len(applied) == 1

    def test_server_cursors_are_suppressed_during_the_drag(self):
        """ the real `set_windows_cursor` must leave the drag cursor alone """
        from xpra.client.gtk3.client_base import GTKXpraClient
        window, _ = self.make_window()
        gdkwin = window.drawing_area.get_window()
        applied = []
        gdkwin.set_cursor = applied.append

        class FakeClient:
            set_windows_cursor = GTKXpraClient.set_windows_cursor

            @staticmethod
            def get_subsystem(_name):
                return None

        client = FakeClient()
        cursor_data = ("raw", 0, 0, 16, 16, 0, 0, 0x1234, b"\xff" * 1024, "left_ptr")
        client.set_windows_cursor([window], cursor_data)
        assert len(applied) == 1, f"{applied=}"
        window.set_moveresize_cursor(MoveResize.SIZE_TOP)
        assert window.moveresize_cursor == "n-resize"
        set_during_drag = len(applied)
        client.set_windows_cursor([window], cursor_data)
        client.set_windows_cursor([window], ())
        assert len(applied) == set_during_drag, "the server cursor was applied during the drag"
        # but the cursor data is still recorded, so we can restore it:
        assert window.cursor_data == ()

    def test_unknown_directions_set_no_cursor(self):
        window, applied = self.make_window()
        for direction in (MoveResize.SIZE_KEYBOARD, MoveResize.CANCEL):
            with self.subTest(direction=direction):
                window.set_moveresize_cursor(direction)
                assert window.moveresize_cursor == ""
        window.cancel_moveresize_cursor()
        assert not applied, "nothing to restore"

    def test_button_release_polling_ends_the_drag(self):
        window, applied = self.make_window()
        window.button_pressed[1] = 1
        window.set_moveresize_cursor(MoveResize.SIZE_BOTTOMRIGHT)
        # still held down:
        window.do_poll_buttons((0, 0), [], (1, ))
        assert window.moveresize_cursor == "se-resize"
        # released:
        window.do_poll_buttons((0, 0), [], ())
        assert window.moveresize_cursor == ""
        assert len(applied) == 1

    def test_keyboard_drag_ends_on_escape_and_focus_loss(self):
        for end in ("escape", "focus"):
            with self.subTest(end=end):
                window, applied = self.make_window()
                # a keyboard move has no button to release:
                window.set_moveresize_cursor(MoveResize.MOVE_KEYBOARD)
                assert window.moveresize_cursor == "move"
                window.do_poll_buttons((0, 0), [], ())
                assert window.moveresize_cursor == "move", "no button was pressed"
                if end == "escape":
                    Gdk = gi_import("Gdk")
                    event = Gdk.EventKey()
                    event.keyval = Gdk.KEY_Escape
                    # no fallback drag in progress, so the event must propagate:
                    assert window.key_may_break_moveresize(window, event) is False
                else:
                    assert window.focus_may_break_moveresize(window, None) is False
                assert window.moveresize_cursor == ""
                assert len(applied) == 1


if __name__ == "__main__":
    unittest.main()
