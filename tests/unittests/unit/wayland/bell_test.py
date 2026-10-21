#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import unittest
from types import ModuleType
from unittest.mock import Mock, patch

from xpra.wayland.server.subsystem.bell import WaylandBellServer


class FakeOptions:
    bell = True


def make_bell_server(*window_sources):
    server = Mock()
    server.window_sources.return_value = window_sources
    bell = WaylandBellServer(server)
    bell.init(FakeOptions())
    return bell


def patched_surfaces(surfaces: dict):
    # `xpra.wayland.server.wayland_surface` is a compiled module which may not
    # be built, and `bell_event` imports it lazily - so stand in for it:
    module = ModuleType("xpra.wayland.server.wayland_surface")
    module.surfaces = surfaces
    return patch.dict(sys.modules, {"xpra.wayland.server.wayland_surface": module})


class WaylandBellTest(unittest.TestCase):

    def test_connect_compositor_subscribes_to_bell(self):
        compositor = Mock()
        bell = make_bell_server()
        bell.connect_compositor(compositor)
        compositor.connect.assert_called_once_with("bell", bell.bell_event)

    def test_ring_without_surface_uses_wid_0(self):
        source = Mock()
        bell = make_bell_server(source)
        with patched_surfaces({}):
            bell.bell_event(0)
        source.bell.assert_called_once_with(0, 0, 100, 0, 0, 0, 0, "")

    def test_ring_on_known_surface_uses_its_wid(self):
        source = Mock()
        bell = make_bell_server(source)
        surface = Mock()
        surface.wid = 7
        with patched_surfaces({0x1234: surface}):
            bell.bell_event(0x1234)
        self.assertEqual(source.bell.call_args[0][0], 7)

    def test_ring_on_unknown_surface_falls_back_to_wid_0(self):
        source = Mock()
        bell = make_bell_server(source)
        with patched_surfaces({}):
            bell.bell_event(0x1234)
        self.assertEqual(source.bell.call_args[0][0], 0)

    def test_disabled_bell_is_not_forwarded(self):
        source = Mock()
        bell = make_bell_server(source)
        bell.bell = False
        with patched_surfaces({}):
            bell.bell_event(0)
        source.bell.assert_not_called()


def main():
    unittest.main()


if __name__ == "__main__":
    main()
