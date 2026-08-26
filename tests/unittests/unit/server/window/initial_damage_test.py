#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.server.window.compress import WindowSource
from xpra.server.window.subsurface_source import SubsurfaceWindowSource
from xpra.server.window.video_compress import WindowVideoSource
from xpra.util.objects import typedict


class InitialDamageTest(unittest.TestCase):

    @staticmethod
    def make_source(source_class: type[WindowVideoSource] = WindowVideoSource) -> WindowVideoSource:
        source = object.__new__(source_class)
        source.wid = 1
        source._client_csc_modes_resolved = False
        source.is_OR = False
        source.is_tray = False
        source.is_shadow = False
        source.common_video_encodings = ("h264",)
        source.non_video_encodings = ()
        source.full_csc_modes = typedict()
        return source

    @staticmethod
    def damage(source: WindowVideoSource) -> bool:
        with patch.object(WindowSource, "damage") as damage:
            source.damage(0, 0, 800, 600)
        return damage.called

    def set_properties(self, source: WindowVideoSource, properties: dict) -> None:
        with patch.object(WindowSource, "set_client_properties") as set_properties:
            source.set_client_properties(typedict(properties))
        set_properties.assert_called_once()

    def test_video_only_damage_waits_for_window_csc_modes(self):
        source = self.make_source()

        self.assertFalse(self.damage(source))

        self.set_properties(source, {"event": "map"})
        self.assertTrue(self.damage(source))

    def test_explicit_empty_window_csc_modes_resolve_state(self):
        source = self.make_source()

        self.set_properties(source, {"encoding.full_csc_modes": {}})

        self.assertTrue(source._client_csc_modes_resolved)
        self.assertTrue(self.damage(source))

    def test_subsurface_damage_does_not_wait_for_toplevel_map(self):
        source = self.make_source(SubsurfaceWindowSource)
        source.parent_wid = 9

        self.assertTrue(self.damage(source))

    def test_safe_initial_damage_paths_remain_immediate(self):
        cases = {
            "picture fallback": {"non_video_encodings": ("rgb24",)},
            "global csc modes": {"full_csc_modes": typedict({"h264": ("YUV420P",)})},
            "override redirect": {"is_OR": True},
            "tray": {"is_tray": True},
            "shadow": {"is_shadow": True},
            "no video encoding": {"common_video_encodings": ()},
        }
        for name, values in cases.items():
            with self.subTest(name=name):
                source = self.make_source()
                for key, value in values.items():
                    setattr(source, key, value)
                self.assertTrue(self.damage(source))


if __name__ == "__main__":
    unittest.main()
