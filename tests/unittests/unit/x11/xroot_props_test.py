#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch
from types import SimpleNamespace

from xpra.x11 import xroot_props as root
from xpra.x11.error import XError
from unit.x11.property_test_util import PropertyTestCase, ROOT_XID

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

            def __init__(self, monitors: dict):
                self.monitors = monitors
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


class TestRootProperties(PropertyTestCase):

    def test_desktop_settings_roundtrip(self):
        self.assertEqual(root.get_current_desktop(), 0)
        self.assertEqual(root.get_number_of_desktops(), 1)
        self.assertEqual(root.get_desktop_names(), ("Main",))
        root.set_desktop_list(["Main", "λ"])
        self.assertEqual(root.get_number_of_desktops(), 2)
        self.assertEqual(root.get_desktop_names(), ["Main", "λ"])
        root.set_current_desktop(1)
        self.assertEqual(root.get_current_desktop(), 1)
        root.set_desktop_geometry(2560, 1440)
        self.assertEqual(root.get_desktop_geometry(), (2560, 1440))
        root.set_desktop_viewport(5, 10)
        self.assertEqual(root.root_array_get("_NET_DESKTOP_VIEWPORT", "u32"), [5, 10])
        root.root_del("_NET_CURRENT_DESKTOP")
        self.assertEqual(root.get_current_desktop(), 0)
        root.root_array_set("_NET_DESKTOP_GEOMETRY", "u32", [1, 2, 3])
        self.assertEqual(root.get_desktop_geometry(), (3840, 2160))
        root.root_del("_NET_DESKTOP_GEOMETRY")
        self.assertEqual(root.get_desktop_geometry(), (3840, 2160))

    def test_supported_atoms(self):
        from xpra.x11.common import NET_SUPPORTED
        root.set_supported()
        self.assertEqual(root.root_array_get("_NET_SUPPORTED", "atom"), list(NET_SUPPORTED))

    def test_workareas_on_each_desktop_and_stale_cleanup(self):
        monitors = [(0, 24, 1920, 1056), (1920, 0, 1920, 1080)]
        root.set_desktop_list(["one", "two", "three"])
        root.set_workareas(monitors)
        for desktop in range(3):
            root.set_current_desktop(desktop)
            self.assertEqual(root.get_workareas(), tuple(monitors))
        root.set_workareas(monitors[:1], desktops=1)
        self.assertIsNone(root.root_array_get("_GTK_WORKAREAS_D1", "u32"))
        self.assertIsNone(root.root_array_get("_GTK_WORKAREAS_D2", "u32"))
        root.set_current_desktop(0)
        self.assertEqual(root.get_workarea(), monitors[0])
        root.set_workareas([], desktops=1)
        self.assertIsNone(root.root_array_get("_GTK_WORKAREAS_D0", "u32"))
        self.assertEqual(root.get_workareas(), ())

    def test_screen_workarea_fallbacks(self):
        root.set_workarea(0, 20, 3840, 2140)
        self.assertEqual(root.get_net_workareas(), ((0, 20, 3840, 2140),))
        self.assertEqual(root.get_workarea(), (0, 20, 3840, 2140))
        # Multiple GTK rectangles describe monitors, not desktops.
        root.set_workareas([(0, 20, 1920, 1060), (1920, 0, 1920, 1080)], desktops=1)
        root.root_array_set("_NET_WORKAREA", "u32", [0, 20, 3840, 2140, 0, 40, 3840, 2120])
        root.set_current_desktop(1)
        self.assertEqual(root.get_workarea(), (0, 40, 3840, 2120))
        root.set_current_desktop(9)
        self.assertEqual(root.get_workarea(), (0, 0, 3840, 2160))
        with patch.object(root, "get_current_desktop", return_value=-1):
            self.assertEqual(root.get_workarea(), (0, 0, 3840, 2160))
            self.assertEqual(root.get_gtk_workareas(), ((0, 20, 1920, 1060), (1920, 0, 1920, 1080)))
        root.root_del("_NET_WORKAREA")
        self.assertEqual(root.get_net_workareas(), ())

    def test_icc_profiles_and_versions(self):
        self.assertEqual(root.get_icc_profile(), b"")
        self.assertEqual(root.get_icc_version(), 0)
        self.assertEqual(root.get_icc_data(), {})
        for bits in (8, 16, 32):
            with self.subTest(bits=bits):
                root.root_array_set("_ICC_PROFILE", f"u{bits}", [0, 1, 127, 255])
                root.root_set("_ICC_PROFILE_IN_X_VERSION", f"u{bits}", 4)
                self.assertEqual(root.get_icc_data(), {"source": "_ICC_PROFILE", "data": b"\0\x01\x7f\xff", "version": 4})
        root.root_del("_ICC_PROFILE_IN_X_VERSION")
        self.assertEqual(root.get_icc_data(), {"source": "_ICC_PROFILE", "data": b"\0\x01\x7f\xff"})
        root.root_array_set("_ICC_PROFILE", "u8", [])
        self.assertEqual(root.get_icc_profile(), b"")

    def test_invalid_icc_properties(self):
        for xtype, fmt in (("STRING", 8), ("CARDINAL", 64)):
            with self.subTest(xtype=xtype, fmt=fmt), patch.object(root, "log") as log:
                self.window.XChangeProperty(ROOT_XID, "_ICC_PROFILE", xtype, fmt, b"data")
                self.assertEqual(root.get_icc_profile(), b"")
                log.warn.assert_called_once()
        root.root_array_set("_ICC_PROFILE", "u16", [256])
        with patch.object(root, "log") as log:
            self.assertEqual(root.get_icc_profile(), b"")
            log.error.assert_called_once()
        with patch.object(self.window, "GetWindowPropertyType", side_effect=XError("window gone")):
            self.assertEqual(root.get_icc_profile(), b"")

    def test_keyboard_rules_and_resources(self):
        self.assertEqual(root.get_xkb_rules_names(), ())
        self.assertEqual(root.get_xresources(), {})
        root.root_set("_XKB_RULES_NAMES", "latin1", "evdev\0pc104\0gb,us\0,\0\0")
        self.assertEqual(root.get_xkb_rules_names(), ("evdev", "pc104", "gb,us", ",", "", ""))
        root.root_set("RESOURCE_MANAGER", "latin1", "Xft.dpi:\t144\n\ninvalid\nName:\tvalue:\tmore\nXft.dpi:\t192\n")
        self.assertEqual(root.get_xresources(), {"Xft.dpi": "192", "Name": "value:\tmore"})

    def test_root_property_watcher(self):
        from xpra.x11 import dispatch
        from xpra.x11.bindings.core import constants
        original_receivers = dispatch.event_receivers_map.get(ROOT_XID, set()).copy()
        watcher = root.XRootPropWatcher(["_NET_CURRENT_DESKTOP", "RESOURCE_MANAGER"], ["_GTK_WORKAREAS_D"])
        self.addCleanup(watcher.cleanup)
        self.assertEqual(repr(watcher), "XRootPropWatcher")
        self.assertEqual(self.window.event_mask, 4 | constants["PropertyChangeMask"])
        self.assertIn(watcher, dispatch.event_receivers_map[ROOT_XID])
        changed = []
        watcher.connect("root-prop-changed", lambda _watcher, name: changed.append(name))
        for atom in ("_NET_CURRENT_DESKTOP", "_GTK_WORKAREAS_D3", "UNRELATED"):
            watcher.do_x11_property_notify_event(SimpleNamespace(atom=atom))
        self.assertEqual(changed, ["_NET_CURRENT_DESKTOP", "_GTK_WORKAREAS_D3"])
        watcher.notify_all()
        self.assertEqual(changed[-2:], ["_NET_CURRENT_DESKTOP", "RESOURCE_MANAGER"])
        watcher.cleanup()
        self.assertEqual(self.window.event_mask, 4)
        self.assertEqual(dispatch.event_receivers_map.get(ROOT_XID, set()), original_receivers)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
