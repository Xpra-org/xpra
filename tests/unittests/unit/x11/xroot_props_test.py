#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

# pylint: disable=import-outside-toplevel


class TestXRootProps(unittest.TestCase):

    def test_split_rects(self):
        from xpra.x11.xroot_props import split_rects
        # empty or invalid lengths are discarded:
        for invalid in ((), [], (1, ), (1, 2, 3), (1, 2, 3, 4, 5)):
            self.assertEqual(split_rects(invalid), (), f"expected no rectangles from {invalid}")
        self.assertEqual(split_rects((0, 28, 3840, 2107)), ((0, 28, 3840, 2107), ))
        self.assertEqual(split_rects([0, 0, 1920, 1040, 1920, 0, 1920, 1080]),
                         ((0, 0, 1920, 1040), (1920, 0, 1920, 1080)))
        self.assertEqual(len(split_rects(list(range(12)))), 3)

    def test_normalized_monitors_workarea(self):
        from xpra.util.screen import MonitorLayout
        # a monitor to the left of the primary one, with a panel at the top:
        monitors = {
            0: {"geometry": (-1920, 0, 1920, 1080), "workarea": (-1920, 24, 1920, 1056)},
            1: {"geometry": (0, 0, 1920, 1080), "workarea": (0, 0, 1920, 1080)},
        }
        layout = MonitorLayout(monitors)
        normalized = layout.normalized_monitors(monitors)
        # both the geometry and the workarea must be rebased by the same amount:
        self.assertEqual(normalized[0]["geometry"], (0, 0, 1920, 1080))
        self.assertEqual(normalized[0]["workarea"], (0, 24, 1920, 1056))
        self.assertEqual(normalized[1]["geometry"], (1920, 0, 1920, 1080))
        self.assertEqual(normalized[1]["workarea"], (1920, 0, 1920, 1080))

    def test_client_workareas(self):
        from xpra.server.source.display import DisplayConnection
        from xpra.util.screen import MonitorLayout

        class FakeSource:
            """ just enough of a `DisplayConnection` to exercise the workarea getters """
            get_monitor_definitions = DisplayConnection.get_monitor_definitions
            get_normalized_monitor_definitions = DisplayConnection.get_normalized_monitor_definitions
            get_client_workarea = DisplayConnection.get_client_workarea
            get_client_workareas = DisplayConnection.get_client_workareas

            def __init__(self, monitors: dict, screen_sizes=()):
                self.monitors = monitors
                self.screen_sizes = list(screen_sizes)
                self.monitor_layout = MonitorLayout(monitors)

        # two side by side monitors, only the left one has a bottom panel:
        ss = FakeSource({
            0: {"geometry": (0, 0, 1920, 1080), "workarea": (0, 0, 1920, 1040)},
            1: {"geometry": (1920, 0, 1920, 1080), "workarea": (1920, 0, 1920, 1080)},
        })
        self.assertEqual(ss.get_client_workareas(), [(0, 0, 1920, 1040), (1920, 0, 1920, 1080)])
        # the single rectangle used for `_NET_WORKAREA` loses the panel,
        # which is exactly why we also export `_GTK_WORKAREAS_D#`:
        workarea = ss.get_client_workarea()
        self.assertEqual((workarea.x, workarea.y, workarea.width, workarea.height), (0, 0, 3840, 1080))

        # monitors without any workarea:
        ss = FakeSource({0: {"geometry": (0, 0, 1920, 1080)}})
        self.assertEqual(ss.get_client_workareas(), [])

        # legacy `screen_sizes` clients: the per-monitor workarea is at [7:11]
        from xpra.net.common import BACKWARDS_COMPATIBLE
        if BACKWARDS_COMPATIBLE:
            ss = FakeSource({}, ((
                "screen0", 1920, 1080, 508, 285,
                (("monitor0", 0, 0, 1920, 1080, 508, 285, 0, 24, 1920, 1056), ),
                0, 24, 1920, 1056,
            ), ))
            self.assertEqual(ss.get_client_workareas(), [(0, 24, 1920, 1056)])


def main():
    unittest.main()


if __name__ == '__main__':
    main()
