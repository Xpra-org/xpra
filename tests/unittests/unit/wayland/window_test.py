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
# `load_window_server_class` restores `sys.modules` wholesale, which drops every
# module imported inside it - including `gi.repository.GObject`, which cannot be
# imported a second time. So anything needing it has to be imported before that:
from xpra.wayland.server.models.subsurface_window import SubsurfaceWindow


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

    def test_commit_exports_surface_opaque_region(self):
        window = Mock()
        server = self.make_server(window)
        surface = server.get_surface.return_value
        surface.get_opaque_region.return_value = ((0, 0, 100, 80),)

        WaylandWindowServer.commit(server, 7, True, (100, 80), (), [])

        server.update_opaque_region.assert_called_once_with(window, surface)
        WaylandWindowServer.update_opaque_region(window, surface)
        window._updateprop.assert_called_with("opaque-region", ((0, 0, 100, 80),))

    def test_commit_exports_surface_content_type(self):
        window = Mock()
        server = self.make_server(window)
        surface = server.get_surface.return_value
        surface.get_content_types.return_value = ("picture",)

        WaylandWindowServer.commit(server, 7, True, (100, 80), (), [])

        server.update_content_types.assert_called_once_with(window, surface)
        WaylandWindowServer.update_content_types(window, surface)
        window._updateprop.assert_called_with("content-types", ("picture",))

    def test_wayland_content_type_mapping(self):
        from xpra.wayland.server.wayland_surface import WAYLAND_CONTENT_TYPE_TO_XPRA
        self.assertEqual(WAYLAND_CONTENT_TYPE_TO_XPRA, {
            "photo": "picture",
            "video": "video",
            "game": "video",
        })

    def test_opaque_source_buffer_uses_x_pixel_format(self):
        from xpra.wayland.server.wayland_surface import get_capture_pixel_format
        xrgb = int.from_bytes(b"XR24", "little")
        xbgr = int.from_bytes(b"XB24", "little")
        argb = int.from_bytes(b"AR24", "little")
        abgr = int.from_bytes(b"AB24", "little")

        # Retain wlroots' channel order, but discard the meaningless alpha.
        self.assertEqual(get_capture_pixel_format(argb, xrgb), "BGRX")
        self.assertEqual(get_capture_pixel_format(abgr, xrgb), "RGBX")
        self.assertEqual(get_capture_pixel_format(argb, xbgr), "BGRX")
        self.assertEqual(get_capture_pixel_format(abgr, xbgr), "RGBX")

        # An alpha-capable source must remain alpha-capable.
        self.assertEqual(get_capture_pixel_format(argb, argb), "BGRA")
        self.assertEqual(get_capture_pixel_format(abgr, argb), "RGBA")

    def test_surface_image_publishes_the_buffer_alpha_before_the_image(self):
        for pixel_format, has_alpha in (
                ("RGBA", True), ("BGRA", True),
                ("RGBX", False), ("BGRX", False),
        ):
            window = Mock()
            server = self.make_server(window)
            server.pending_popups = {}
            image = Mock()
            image.get_pixel_format.return_value = pixel_format

            WaylandWindowServer.surface_image(server, 7, image)

            # `has-alpha` is the capability the client's backing is built from and must
            # not follow the buffers, and the frame value has to be published before the
            # image, so the encoding selection is current when the `commit` becomes damage:
            self.assertEqual(window._updateprop.call_args_list, [
                (("frame-has-alpha", has_alpha), ),
                (("image", image), ),
            ], f"unexpected properties published for a {pixel_format!r} buffer")

    def test_subsurface_alpha_is_its_own_buffer_and_not_the_parent(self):
        # a translucent parent with an opaque video plane in a subsurface
        # is the canonical use for one, so the child must not inherit its parent:
        facade = SubsurfaceWindow(320, 240, has_alpha=True, depth=32)
        changes = []
        facade.connect("notify::frame-has-alpha",
                       lambda *_args: changes.append(facade.get_property("frame-has-alpha")))
        for pixel_format, has_alpha in (("BGRX", False), ("BGRA", True), ("BGRA", True)):
            image = Mock()
            image.get_pixel_format.return_value = pixel_format
            facade.set_image(image)
            self.assertEqual(facade.get_property("frame-has-alpha"), has_alpha,
                             f"for a {pixel_format!r} buffer")
            # the exported capability must not follow the buffer:
            self.assertTrue(facade.has_alpha())
        # an unchanged format must not notify:
        self.assertEqual(changes, [False, True])

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
