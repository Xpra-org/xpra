#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace

from xpra.client.mixins.window_manager import WindowClient


class GeometryClient(WindowClient):

    def _ui_event(self):
        pass

    def make_new_window(self, wid, wx, wy, ww, wh, bw, bh, metadata, override_redirect, client_properties):
        window = SimpleNamespace(
            _pos=(wx, wy), size=(ww, wh), backing_size=(bw, bh), sp=self.sp,
            client_properties=client_properties,
        )
        self._id_to_window[wid] = window
        return window


class WindowGeometryTest(unittest.TestCase):

    def setUp(self):
        self.client = GeometryClient()
        self.client.sx = lambda x: x * 2
        self.client.sy = lambda y: y * 2
        self.client.sp = lambda x, y: (x * 2, y * 2)
        self.client._id_to_window[3] = SimpleNamespace(_pos=(100, 200), sp=self.client.sp)

    def create_window(self, wid, **metadata):
        return self.client._process_new_common((
            "new-override-redirect", wid, 10, 20, 120, 80, metadata, {"workspace": 2},
        ), True)

    def test_relative_geometry_is_only_scaled_once(self):
        popup = self.create_window(7, parent=3, **{"relative-position": (12, 23)})
        self.assertEqual(popup._pos, (124, 246))
        submenu = self.create_window(8, parent=7, **{"relative-position": (5, 6)})
        self.assertEqual(submenu._pos, (134, 258))
        self.assertEqual(popup.size, (240, 160))
        self.assertEqual(popup.backing_size, (120, 80))
        self.assertEqual(popup.client_properties, {"workspace": 2})

    def test_absolute_geometry_is_scaled(self):
        self.assertEqual(self.create_window(7)._pos, (20, 40))

    def test_missing_parent_uses_absolute_geometry(self):
        popup = self.create_window(7, parent=99, **{"relative-position": (12, 23)})
        self.assertEqual(popup._pos, (20, 40))


if __name__ == "__main__":
    unittest.main()
