#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import math
from collections.abc import Callable
import cairo

from xpra.common import noop
from xpra.exit_codes import ExitCode
from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.os_util import gi_import

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GLib = gi_import("GLib")


def _fmt_time(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60}:{s % 60:02d}"


class TimelineScale(Gtk.DrawingArea):
    """
    A custom timeline bar that draws:
      - a filled elapsed region
      - amber ticks for every event
      - taller green ticks for sync-point events
      - a draggable white playhead
    """
    HEIGHT = 52
    TRACK_H = 8
    TICK_H_EVENT = 10    # amber, below track
    TICK_H_SYNC = 22     # green, straddles the track

    def __init__(self, total_ms: int):
        super().__init__()
        self.total_ms = max(1, total_ms)
        self.current_ms = 0
        self.event_times: list[int] = []
        self.sync_times: list[int] = []
        self._seek_cb = noop
        self._dragging = False

        self.set_size_request(-1, self.HEIGHT)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
        self.connect("draw", self._on_draw)
        self.connect("button-press-event", self._on_press)
        self.connect("button-release-event", self._on_release)
        self.connect("motion-notify-event", self._on_motion)

    def set_seek_callback(self, cb: Callable) -> None:
        self._seek_cb = cb

    def set_events_data(self, event_times: list[int], sync_times: list[int]) -> None:
        self.event_times = event_times
        self.sync_times = sync_times
        self.queue_draw()

    def set_position(self, ms: int) -> None:
        if self.current_ms != ms:
            self.current_ms = ms
            self.queue_draw()

    # ── geometry helpers ──────────────────────────────────────────────────────

    def _track_rect(self, alloc_w: int) -> tuple[int, int, int, int]:
        pad = 14
        ty = (self.HEIGHT - self.TRACK_H) // 2
        return pad, ty, alloc_w - 2 * pad, self.TRACK_H

    def _ms_to_x(self, ms: int, tx: int, tw: int) -> float:
        return tx + (ms / self.total_ms) * tw

    def _x_to_ms(self, x: float, tx: int, tw: int) -> int:
        return int(max(0.0, min(1.0, (x - tx) / tw)) * self.total_ms)

    # ── drawing ───────────────────────────────────────────────────────────────

    def _on_draw(self, widget, cr: cairo.Context) -> None:
        a = widget.get_allocation()
        tx, ty, tw, th = self._track_rect(a.width)
        mid_y = ty + th / 2

        # Background track
        cr.set_source_rgb(0.18, 0.18, 0.18)
        self._rounded_rect(cr, tx, ty, tw, th, th / 2)
        cr.fill()

        # Elapsed fill
        ew = (self.current_ms / self.total_ms) * tw
        cr.set_source_rgb(0.22, 0.50, 0.88)
        self._rounded_rect(cr, tx, ty, max(0, ew), th, th / 2)
        cr.fill()

        # Amber ticks – every event (drawn below track)
        tick_y = ty + th + 3
        cr.set_source_rgba(0.95, 0.72, 0.12, 0.50)
        for t in self.event_times:
            x = self._ms_to_x(t, tx, tw)
            cr.rectangle(x - 0.5, tick_y, 1, self.TICK_H_EVENT)
            cr.fill()

        # Green ticks – sync points (straddle the track, taller)
        sync_y = mid_y - self.TICK_H_SYNC / 2
        cr.set_source_rgba(0.18, 0.88, 0.42, 0.85)
        for t in self.sync_times:
            x = self._ms_to_x(t, tx, tw)
            cr.rectangle(x - 1, sync_y, 2, self.TICK_H_SYNC)
            cr.fill()

        # Playhead knob
        px = self._ms_to_x(self.current_ms, tx, tw)
        cr.set_source_rgb(1.0, 1.0, 1.0)
        cr.arc(px, mid_y, 7, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgb(0.22, 0.50, 0.88)
        cr.arc(px, mid_y, 4.5, 0, 2 * math.pi)
        cr.fill()

    @staticmethod
    def _rounded_rect(cr, x, y, w, h, r):
        if w <= 0:
            return
        r = min(r, w / 2, h / 2)
        cr.new_path()
        cr.arc(x + r,     y + r,     r, math.pi,         3 * math.pi / 2)
        cr.arc(x + w - r, y + r,     r, 3 * math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0,               math.pi / 2)
        cr.arc(x + r,     y + h - r, r, math.pi / 2,     math.pi)
        cr.close_path()

    # ── mouse interaction ─────────────────────────────────────────────────────

    def _on_press(self, _widget, event) -> bool:
        if event.button == 1:
            self._dragging = True
            self._emit_seek(event.x)
        return True

    def _on_release(self, _widget, event) -> bool:
        if event.button == 1:
            self._dragging = False
        return True

    def _on_motion(self, _widget, event) -> bool:
        if self._dragging:
            self._emit_seek(event.x)
        return True

    def _emit_seek(self, x: float) -> None:
        a = self.get_allocation()
        tx, _, tw, _ = self._track_rect(a.width)
        self._seek_cb(self._x_to_ms(x, tx, tw))


class ControlWindow:
    """Floating playback-control window."""

    def __init__(self, replay):
        self.replay = replay

        win = Gtk.Window(title="Xpra Replay")
        win.set_default_size(720, 120)
        win.set_resizable(True)
        win.set_keep_above(True)
        win.connect("delete-event", lambda *_: replay.quit(ExitCode.OK))
        self.window = win

        icon = get_icon_pixbuf("gears")
        if icon:
            self.window.set_icon(icon)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        outer.set_margin_top(10)
        outer.set_margin_bottom(10)
        outer.set_margin_start(14)
        outer.set_margin_end(14)
        win.add(outer)

        # Timeline
        self.timeline = TimelineScale(replay.last_timestamp)
        self.timeline.set_seek_callback(self._on_seek)
        outer.pack_start(self.timeline, False, False, 0)

        # Controls row
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        outer.pack_start(row, False, False, 0)

        self.play_btn = Gtk.Button(label="⏸")
        self.play_btn.set_tooltip_text("Play / Pause")
        self.play_btn.connect("clicked", lambda _: self._on_play_pause())
        row.pack_start(self.play_btn, False, False, 0)

        self.time_label = Gtk.Label(label="0:00 / 0:00")
        self.time_label.set_halign(Gtk.Align.START)
        row.pack_start(self.time_label, True, True, 0)

        row.pack_start(Gtk.Label(label="Speed ×"), False, False, 0)
        adj = Gtk.Adjustment(value=1.0, lower=0.25, upper=8.0,
                             step_increment=0.25, page_increment=1.0)
        self.speed_spin = Gtk.SpinButton(adjustment=adj, digits=2)
        self.speed_spin.connect("value-changed", self.speed_changed)
        row.pack_start(self.speed_spin, False, False, 0)

        self.replay.end_of_replay = self.end_of_replay

        win.show_all()
        GLib.timeout_add(100, self._tick)

    def end_of_replay(self):
        if self.replay.is_playing:
            self.replay.toggle_play_pause()
        self.replay.seek(0)

    def speed_changed(self, *args) -> None:
        self.replay.rate = self.speed_spin.get_value()

    def set_events_data(self, event_times: list[int], sync_times: list[int]) -> None:
        self.timeline.set_events_data(event_times, sync_times)

    # ── callbacks ─────────────────────────────────────────────────────────────

    def _on_play_pause(self) -> None:
        self.replay.toggle_play_pause()

    def _on_seek(self, ms: int) -> None:
        self.replay.seek(ms)

    def _tick(self) -> bool:
        """Runs every 100 ms to refresh the UI."""
        r = self.replay
        ms, total = r.time_index, r.last_timestamp
        self.timeline.set_position(ms)
        self.time_label.set_text(f"{_fmt_time(ms)} / {_fmt_time(total)}")
        self.play_btn.set_label("▶" if not r.is_playing else "⏸")
        return True  # keep repeating


def do_main(options) -> int:
    from xpra.platform import program_context
    with program_context("Replay", "Replay"):
        if "-v" in sys.argv:
            from xpra.log import enable_debug_for
            enable_debug_for("util")

        from xpra.client.gtk3.replay import GtkReplay
        replay = GtkReplay(options)
        replay.load()
        ControlWindow(replay)
        return replay.run()


def main() -> int:
    from xpra.scripts.config import make_defaults_struct
    options = make_defaults_struct()
    return do_main(options)


if __name__ == "__main__":
    v = main()
    sys.exit(v)
