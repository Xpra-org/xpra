#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import unittest
from types import ModuleType
from types import SimpleNamespace
from unittest.mock import Mock, patch


def load_window_server_class():
    modules = {}
    for module_name, names in (
            ("xpra.codecs.image", {"ImageWrapper": object}),
            ("xpra.server.common", {"get_sources_by_type": Mock()}),
            ("xpra.server.source.window", {"WindowsConnection": object}),
            ("xpra.util.gobject", {"to_gsignals": lambda signals: {}}),
            ("xpra.util.objects", {"typedict": dict}),
            ("xpra.wayland.compositor", {"WaylandCompositor": object}),
            ("xpra.wayland.surface", {"Surface": object}),
            ("xpra.wayland.subsurface", {"Subsurface": object}),
            ("xpra.wayland.popup", {"Popup": object}),
            ("xpra.wayland.output", {"Output": object}),
            ("xpra.wayland.models.window", {"Window": object}),
            ("xpra.wayland.models.subsurface_window", {"SubsurfaceWindow": object}),
            ("xpra.server.base", {"ServerBase": type("ServerBase", (), {"__signals__": {}})}),
            ("xpra.net.common", {"Packet": object}),
            ("xpra.net.packet_type", {"WINDOW_CREATE": "window-create"}),
            ("xpra.common", {"noop": lambda: None}),
            ("xpra.constants", {"MoveResize": object, "SOURCE_INDICATION_NORMAL": 0}),
            ("xpra.os_util", {"gi_import": lambda name: SimpleNamespace(GObject=type("GObject", (), {"GObject": object}), GLib=object, type_register=lambda cls: None)}),
            ("xpra.log", {"Logger": lambda *args: Mock()}),
    ):
        module = ModuleType(module_name)
        for name, value in names.items():
            setattr(module, name, value)
        modules[module_name] = module
    with patch.dict(sys.modules, modules):
        try:
            from xpra.wayland.server import WaylandSeamlessServer
        except ImportError:
            # the wayland server is not built / installed
            return None
    return WaylandSeamlessServer


WaylandWindowServer = load_window_server_class()


@unittest.skipUnless(WaylandWindowServer, "wayland server is not available")
class WaylandWindowServerCommitTest(unittest.TestCase):

    @staticmethod
    def make_server(window):
        server = Mock()
        server.get_window.return_value = window
        server.get_surface.return_value = Mock()
        server.subsurface_info = {}
        server.subsurface_facades = {}
        server.window_sources.return_value = ()
        return server

    def test_mapped_empty_damage_acknowledges_after_subsurface_updates(self):
        window = Mock()
        server = self.make_server(window)
        subsource = Mock()
        source = Mock()
        source.subsurface_sources = {2: subsource}
        server.window_sources.return_value = (source,)
        subsurface = (2, 3, 4)

        def check_subsurface_updates():
            surface = server.get_surface.return_value
            server.track_toplevel.assert_called_once_with(surface)
            server.update_size.assert_called_once_with(window, (100, 80))
            self.assertEqual(server.subsurface_info[2], (7, 3, 4))
            subsource.update_geometry.assert_called_once_with(7, 3, 4)

        window.acknowledge_changes.side_effect = check_subsurface_updates
        WaylandWindowServer._commit(server, 7, True, (100, 80), (), [subsurface])

        window.acknowledge_changes.assert_called_once_with()
        server.refresh_window_area.assert_not_called()

    def test_mapped_damage_refreshes_without_immediate_acknowledgement(self):
        window = Mock()
        server = self.make_server(window)
        refreshes = []
        server.refresh_window_area.side_effect = (
            lambda win, x, y, w, h, options: refreshes.append((win, x, y, w, h, dict(options)))
        )

        WaylandWindowServer._commit(server, 7, True, (100, 80),
                                    ((1, 2, 3, 4), (5, 6, 7, 8)), [])

        self.assertEqual(refreshes, [
            (window, 1, 2, 3, 4, {"damage": True, "more": True}),
            (window, 5, 6, 7, 8, {"damage": True, "more": False}),
        ])
        window.acknowledge_changes.assert_not_called()

    def test_unmapped_empty_damage_is_ignored(self):
        window = Mock()
        server = self.make_server(window)

        WaylandWindowServer._commit(server, 7, False, (100, 80), (), [])

        window.acknowledge_changes.assert_not_called()
        server.refresh_window_area.assert_not_called()

    def test_unknown_window_is_ignored(self):
        server = self.make_server(None)

        WaylandWindowServer._commit(server, 7, True, (100, 80), (), [])

        server.get_surface.assert_not_called()
        server.refresh_window_area.assert_not_called()


def main():
    unittest.main()


if __name__ == "__main__":
    main()
