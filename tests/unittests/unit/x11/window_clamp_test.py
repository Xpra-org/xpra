#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.server.source.display import DisplayConnection
from xpra.util.rectangle import rectangle
from xpra.x11.subsystem import window as window_module
from xpra.x11.subsystem.window import SeamlessWindowServer, clamp_to_visible_area


class FakeWindow:

    def __init__(self, geometry, shown=True, tray=False, OR=False):
        self.props = {"client-geometry": geometry, "shown": shown}
        self.tray = tray
        self.OR = OR
        self.updated = 0

    def is_tray(self) -> bool:
        return self.tray

    def is_OR(self) -> bool:
        return self.OR

    def get_property(self, name: str):
        return self.props.get(name)

    def set_property(self, name: str, value) -> None:
        self.props[name] = value

    def _update_client_geometry(self) -> None:
        self.updated += 1


def FakeSource(monitors: dict) -> DisplayConnection:
    ss = DisplayConnection.__new__(DisplayConnection)
    ss.init_state()
    ss.set_monitors(monitors)
    return ss


def monitors(*geometries) -> dict:
    return {i: {"geometry": geometry} for i, geometry in enumerate(geometries)}


class ClampToVisibleAreaTest(unittest.TestCase):

    def clamp(self, x, y, w, h, *areas):
        return clamp_to_visible_area(x, y, w, h, [rectangle(*area) for area in areas])

    def test_visible_window_is_unchanged(self) -> None:
        # straddling two adjacent monitors is fine:
        self.assertEqual(self.clamp(75, 10, 50, 50, (0, 0, 100, 100), (100, 0, 100, 100)), (75, 10))

    def test_moved_to_the_monitor_it_overlaps_the_most(self) -> None:
        # the gap between the two monitors is not visible:
        areas = (0, 0, 100, 100), (150, 0, 100, 100)
        self.assertEqual(self.clamp(60, 10, 100, 50, *areas), (0, 10))
        self.assertEqual(self.clamp(120, 10, 100, 50, *areas), (150, 10))

    def test_offscreen_window_uses_the_first_monitor(self) -> None:
        areas = (100, 0, 100, 100), (0, 0, 100, 100)
        self.assertEqual(self.clamp(300, 300, 50, 50, *areas), (150, 50))
        self.assertEqual(self.clamp(-300, -300, 50, 50, *areas), (100, 0))

    def test_oversized_window_is_aligned_to_the_top_left(self) -> None:
        self.assertEqual(self.clamp(300, 300, 150, 150, (0, 0, 100, 100)), (0, 0))


class TestWindowServer(SeamlessWindowServer):

    def __init__(self):  # pylint: disable=super-init-not-called
        self._id_to_window = {}
        self.sources = []

    def get_sources_by_type(self, subsystem_type=object, exclude=None) -> tuple:
        assert subsystem_type is DisplayConnection
        return tuple(self.sources)


class ClampWindowsToScreenTest(unittest.TestCase):

    def setUp(self) -> None:
        self.server = TestWindowServer()

    def add_window(self, *args, **kwargs) -> FakeWindow:
        window = FakeWindow(*args, **kwargs)
        self.server._id_to_window[len(self.server._id_to_window) + 1] = window
        return window

    def test_clamped_to_the_client_monitors(self) -> None:
        self.server.sources.append(FakeSource(monitors((0, 0, 1000, 800), (1000, 0, 1000, 800))))
        visible = self.add_window((900, 100, 200, 200))
        # in the root window, but mostly below the second monitor:
        hidden = self.add_window((1500, 700, 200, 200))
        self.server.clamp_windows_to_screen(2000, 1200)
        self.assertEqual(visible.get_property("client-geometry"), (900, 100, 200, 200))
        self.assertEqual(visible.updated, 0)
        self.assertEqual(hidden.get_property("client-geometry"), (1500, 600, 200, 200))
        self.assertEqual(hidden.updated, 1)

    def test_clamped_to_the_screen(self) -> None:
        # without monitor data, or with more than one client, use the whole screen:
        for sources in ([], [FakeSource({})], [FakeSource(monitors((0, 0, 100, 100)))] * 2):
            self.server.sources = sources
            window = self.add_window((1900, 50, 200, 200))
            self.server.clamp_windows_to_screen(1920, 1080)
            self.assertEqual(window.get_property("client-geometry"), (1720, 50, 200, 200))

    def test_monitors_with_negative_offsets(self) -> None:
        # the server's screen starts at the client's left-most monitor:
        self.server.sources.append(FakeSource(monitors((-1000, 0, 1000, 800), (0, 0, 1000, 800))))
        window = self.add_window((1900, 50, 200, 200))
        self.server.clamp_windows_to_screen(2000, 800)
        self.assertEqual(window.get_property("client-geometry"), (1800, 50, 200, 200))

    def test_monitors_larger_than_the_screen(self) -> None:
        self.server.sources.append(FakeSource(monitors((0, 0, 2560, 1440))))
        window = self.add_window((2000, 50, 200, 200))
        self.server.clamp_windows_to_screen(1920, 1080)
        self.assertEqual(window.get_property("client-geometry"), (1720, 50, 200, 200))

    def test_skipped_windows(self) -> None:
        tray = self.add_window((5000, 5000, 20, 20), tray=True)
        override_redirect = self.add_window((5000, 5000, 20, 20), OR=True)
        self.server.clamp_windows_to_screen(1920, 1080)
        for window in (tray, override_redirect):
            self.assertEqual(window.get_property("client-geometry"), (5000, 5000, 20, 20))

    def test_update_client_geometry(self) -> None:
        shown = self.add_window((5000, 5000, 20, 20))
        hidden = self.add_window((5000, 5000, 20, 20), shown=False)
        with patch.object(window_module, "CLAMP_UPDATE_GEOMETRY", False):
            disabled = self.add_window((5000, 5000, 20, 20))
            self.server.clamp_windows_to_screen(1920, 1080)
            self.assertEqual(disabled.updated, 0)
            self.assertEqual(disabled.get_property("client-geometry"), (1900, 1060, 20, 20))
        # only once `CLAMP_UPDATE_GEOMETRY` is enabled again:
        shown.set_property("client-geometry", (5000, 5000, 20, 20))
        self.server.clamp_windows_to_screen(1920, 1080)
        self.assertEqual(shown.updated, 1)
        self.assertEqual(hidden.updated, 0)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
