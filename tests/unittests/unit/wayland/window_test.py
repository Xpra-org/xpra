#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import unittest
from types import ModuleType
from unittest.mock import Mock, patch

from xpra.util.objects import typedict


def load_window_server_class():
    modules = {}
    for module_name, class_name in (
            ("xpra.wayland.server.popup", "Popup"),
            ("xpra.wayland.server.subsurface", "Subsurface"),
            ("xpra.wayland.server.surface", "Surface"),
    ):
        module = ModuleType(module_name)
        setattr(module, class_name, type(class_name, (), {}))
        modules[module_name] = module
    with patch.dict(sys.modules, modules):
        from xpra.wayland.server.subsystem.window import WaylandWindowServer
    return WaylandWindowServer


WaylandWindowServer = load_window_server_class()


class WaylandWindowServerInitialWindowTest(unittest.TestCase):

    @staticmethod
    def make_server(geometry):
        server = object.__new__(WaylandWindowServer)
        window = Mock()
        window.is_managed.return_value = True
        window.is_tray.return_value = False
        window.is_OR.return_value = False
        window.get_property.return_value = geometry
        server._id_to_window = {7: window}
        server.client_properties = {}
        return server, window

    def test_zero_size_window_is_announced_once_when_ready(self):
        from xpra.net.packet_type import WINDOW_CREATE

        server, window = self.make_server((0, 0, 0, 0))
        source = Mock(uuid="client")

        with patch.object(WaylandWindowServer, "_do_send_new_window_packet") as send_window:
            server.send_initial_windows(source)
            server.update_size(window, (800, 600))
            window.get_property.return_value = (0, 0, 800, 600)
            server.update_size(window, (800, 600))

        window.hide.assert_not_called()
        source.new_window.assert_not_called()
        source.damage.assert_not_called()
        send_window.assert_called_once_with(
            WINDOW_CREATE, window, (0, 0, 800, 600),
        )

    def test_map_applies_properties_before_first_refresh(self):
        from xpra.net.common import Packet
        from xpra.server.subsystem.window import WindowServer
        from xpra.server.window.compress import WindowSource
        from xpra.server.window.video_compress import WindowVideoSource

        proto = Mock()
        window = Mock()
        surface = Mock()
        server = Mock()
        server.get_window.return_value = window
        server.get_surface.return_value = surface
        source = object.__new__(WindowVideoSource)
        source.wid = 7
        source._client_csc_modes_resolved = False
        source.is_OR = False
        source.is_tray = False
        source.is_shadow = False
        source.common_video_encodings = ("h264",)
        source.non_video_encodings = ()
        source.full_csc_modes = typedict()
        connection = Mock(uuid="client")
        server.get_server_source.return_value = connection
        events = []

        def set_client_properties(_wid, _window, properties):
            events.append("properties")
            source.set_client_properties(properties)

        connection.set_client_properties.side_effect = set_client_properties
        server._set_client_properties.side_effect = (
            lambda *args: WindowServer._set_client_properties(server, *args)
        )
        surface.resize.side_effect = lambda *_args: events.append("resize")
        server.server.compositor.flush.side_effect = lambda: events.append("flush")

        def refresh_window(_window):
            events.append("refresh")
            source.damage(0, 0, 800, 600)

        server.refresh_window.side_effect = refresh_window
        properties = {"encoding.full_csc_modes": {"h264": ("YUV420P",)}}

        with patch.object(WindowSource, "set_client_properties"), \
                patch.object(WindowSource, "damage") as damage:
            source.damage(0, 0, 800, 600)
            damage.assert_not_called()

            WaylandWindowServer._process_map(
                server, proto, Packet("window-map", 7, 0, 0, 800, 600, properties),
            )

        self.assertEqual(events, ["properties", "resize", "flush", "refresh"])
        self.assertTrue(source._client_csc_modes_resolved)
        damage.assert_called_once_with(0, 0, 800, 600, None)
        server._set_client_properties.assert_called_once_with(
            proto, 7, window, properties | {"event": "map"},
        )


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
        facade = Mock()
        subsource = Mock()
        source = Mock()
        source.subsurface_sources = {2: subsource}
        server.subsurface_facades[2] = facade
        server.window_sources.return_value = (source,)
        subsurface = (2, 3, 4, 5, 6, 10, 12)

        def check_subsurface_updates():
            surface = server.get_surface.return_value
            server.track_toplevel.assert_called_once_with(surface)
            server.update_colourspace.assert_called_once_with(window, surface)
            server.update_size.assert_called_once_with(window, (100, 80))
            self.assertEqual(server.subsurface_info[2], (7, 3, 4, 5, 6, 10, 12))
            facade.update_dimensions.assert_called_once_with(5, 6)
            subsource.update_geometry.assert_called_once_with(7, 3, 4, 5, 6, 10, 12)

        window.acknowledge_changes.side_effect = check_subsurface_updates
        WaylandWindowServer.commit(server, 7, True, (100, 80), (), [subsurface])

        window.acknowledge_changes.assert_called_once_with()
        server.refresh_window_area.assert_not_called()

    def test_mapped_damage_refreshes_without_immediate_acknowledgement(self):
        window = Mock()
        server = self.make_server(window)
        refreshes = []
        server.refresh_window_area.side_effect = (
            lambda win, x, y, w, h, options: refreshes.append((win, x, y, w, h, dict(options)))
        )

        WaylandWindowServer.commit(server, 7, True, (100, 80),
                                   ((1, 2, 3, 4), (5, 6, 7, 8)), [])

        self.assertEqual(refreshes, [
            (window, 1, 2, 3, 4, {"damage": True, "more": True}),
            (window, 5, 6, 7, 8, {"damage": True, "more": False}),
        ])
        window.acknowledge_changes.assert_not_called()

    def test_unmapped_empty_damage_is_ignored(self):
        window = Mock()
        server = self.make_server(window)

        WaylandWindowServer.commit(server, 7, False, (100, 80), (), [])

        window.acknowledge_changes.assert_not_called()
        server.refresh_window_area.assert_not_called()

    def test_unknown_window_is_ignored(self):
        server = self.make_server(None)

        WaylandWindowServer.commit(server, 7, True, (100, 80), (), [])

        server.get_surface.assert_not_called()
        server.refresh_window_area.assert_not_called()


class WaylandWindowServerConfigureTest(unittest.TestCase):

    @staticmethod
    def make_server(window, surface):
        server = Mock()
        server.get_window.return_value = window
        server.get_surface.return_value = surface
        return server

    def test_property_only_configure_updates_client_properties(self):
        proto = Mock()
        window = Mock()
        surface = Mock()
        server = self.make_server(window, surface)
        properties = {"encodings.rgb_formats": ("RGBX",)}

        WaylandWindowServer.do_process_window_configure(
            server, proto, 7, typedict({"properties": properties}),
        )

        server._set_client_properties.assert_called_once_with(proto, 7, window, properties)
        surface.resize.assert_not_called()
        surface.frame_done.assert_not_called()
        server.server.compositor.flush.assert_not_called()

    def test_properties_are_applied_before_geometry(self):
        proto = Mock()
        window = Mock()
        surface = Mock()
        server = self.make_server(window, surface)
        properties = {"encodings.rgb_formats": ("RGBX",)}
        events = []
        server._set_client_properties.side_effect = lambda *_args: events.append("properties")
        surface.resize.side_effect = lambda *_args: events.append("resize")
        surface.frame_done.side_effect = lambda: events.append("frame-done")
        server.server.compositor.flush.side_effect = lambda: events.append("flush")

        WaylandWindowServer.do_process_window_configure(
            server,
            proto,
            7,
            typedict({
                "properties": properties,
                "geometry": (10, 20, 800, 600),
            }),
        )

        self.assertEqual(events, ["properties", "resize", "frame-done", "flush"])
        server._set_client_properties.assert_called_once_with(proto, 7, window, properties)
        surface.resize.assert_called_once_with(800, 600)
        surface.frame_done.assert_called_once_with()
        server.server.compositor.flush.assert_called_once_with()

    def test_missing_window_or_surface_is_ignored(self):
        proto = Mock()
        properties = {"encodings.rgb_formats": ("RGBX",)}
        config = typedict({
            "properties": properties,
            "geometry": (10, 20, 800, 600),
        })
        cases = (
            ("window", None, Mock()),
            ("surface", Mock(), None),
        )

        for missing, window, surface in cases:
            with self.subTest(missing=missing):
                server = self.make_server(window, surface)

                WaylandWindowServer.do_process_window_configure(server, proto, 7, config)

                server._set_client_properties.assert_not_called()
                if surface is not None:
                    surface.resize.assert_not_called()
                    surface.frame_done.assert_not_called()
                server.server.compositor.flush.assert_not_called()


def main():
    unittest.main()


if __name__ == "__main__":
    main()
