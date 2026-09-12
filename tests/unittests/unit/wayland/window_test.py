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
from xpra.wayland.server.models import window as window_model
from xpra.wayland.server.models import frame as frame_model
from xpra.server.window.compress import WindowSource


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
        from xpra.wayland.server.subsystem.window import (
            PER_SURFACE_EVENTS, WaylandWindowServer,
        )
    return WaylandWindowServer, PER_SURFACE_EVENTS


WaylandWindowServer, PER_SURFACE_EVENTS = load_window_server_class()


class FakeGLib:
    """ enough of GLib to see which timers a model arms and cancels """

    def __init__(self):
        self.timers: dict[int, tuple[int, object]] = {}
        self.counter = 0

    def timeout_add(self, delay: int, callback, *args) -> int:
        self.counter += 1
        self.timers[self.counter] = (delay, lambda: callback(*args))
        return self.counter

    def source_remove(self, timer: int) -> None:
        assert timer in self.timers, f"removing unknown timer {timer}"
        del self.timers[timer]

    def fire(self, timer: int):
        delay, callback = self.timers.pop(timer)
        return callback()


class WaylandWindowFrameTest(unittest.TestCase):

    def setUp(self):
        self.glib = FakeGLib()
        patcher = patch.object(frame_model, "GLib", self.glib)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.surface = Mock()
        self.display = Mock()
        self.window = window_model.Window({"surface": self.surface, "display": self.display})
        self.window.setup()

    def assertAcknowledged(self, count: int) -> None:
        self.assertEqual(self.surface.frame_done.call_count, count)
        self.assertEqual(self.display.flush_clients.call_count, count)

    def test_app_id_is_dynamic_metadata(self):
        changes = []
        self.assertIn("app-id", self.window.get_dynamic_property_names())
        self.window.connect(
            "notify::app-id",
            lambda window, _pspec: changes.append(window.get_property("app-id")))

        self.window._updateprop("app-id", "com.example.Application")

        self.assertEqual(changes, ["com.example.Application"])

    def only_timer(self):
        self.assertEqual(len(self.glib.timers), 1)
        timer, (delay, _callback) = tuple(self.glib.timers.items())[0]
        return timer, delay

    def test_an_empty_commit_is_answered_at_the_pacing_delay(self):
        # answering from the dispatch which delivered the commit would let the client
        # commit again immediately: this server has no output refresh to pace it
        self.window.schedule_empty_acknowledgement()
        self.assertAcknowledged(0)
        timer, delay = self.only_timer()
        self.assertEqual(delay, frame_model.EMPTY_ACK_DELAY)

        self.assertFalse(self.glib.fire(timer), "the answer must not repeat")

        self.assertAcknowledged(1)
        self.assertFalse(self.glib.timers)

    def test_repeated_empty_commits_share_one_answer(self):
        for _ in range(5):
            self.window.schedule_empty_acknowledgement()
        timer, _delay = self.only_timer()
        self.glib.fire(timer)
        self.assertAcknowledged(1)

    def test_damage_cancels_an_answer_already_scheduled(self):
        # otherwise it would fire while the damage is still in the batch queue
        # and drain that frame's callback with it:
        self.window.schedule_empty_acknowledgement()
        self.window.mark_damage_frame_pending()
        timer, delay = self.only_timer()
        self.assertEqual(delay, frame_model.FRAME_TIMEOUT, "the empty answer should be gone")
        self.assertAcknowledged(0)
        self.window.acknowledge_changes()
        self.assertAcknowledged(1)
        self.assertFalse(self.glib.timers)

    def test_a_frame_we_have_not_sent_holds_back_the_empty_acknowledgement(self):
        # `frame_done` drains every callback queued on the surface, so answering an empty
        # commit now would release the client for the damage we have not sent yet:
        self.window.mark_damage_frame_pending()
        self.window.schedule_empty_acknowledgement()
        self.assertAcknowledged(0)
        self.assertEqual(self.only_timer()[1], frame_model.FRAME_TIMEOUT,
                         "an empty commit must not schedule anything while we owe a frame")
        # the ordinary acknowledgement, from `send_delayed_regions`:
        self.window.acknowledge_changes()
        self.assertAcknowledged(1)
        self.assertFalse(self.glib.timers, "the timeout should have been cancelled")
        # and the guard is gone, so the next empty commit schedules its answer:
        self.window.schedule_empty_acknowledgement()
        self.glib.fire(self.only_timer()[0])
        self.assertAcknowledged(2)

    def test_a_frame_which_is_never_sent_is_acknowledged_by_the_timeout(self):
        self.window.mark_damage_frame_pending()
        timer, delay = self.only_timer()
        self.assertEqual(delay, frame_model.FRAME_TIMEOUT)

        self.assertFalse(self.glib.fire(timer), "the timeout must not repeat")

        self.assertAcknowledged(1)
        self.assertFalse(self.glib.timers)
        # firing must clear the timer id before acknowledging,
        # or the cancellation would remove a source which is already gone:
        self.assertEqual(self.window._damage_frame_timer, 0)

    def test_later_damage_does_not_push_the_deadline_back(self):
        # a client which renders on its own timer rather than waiting for the callbacks
        # would otherwise keep the deadline out of reach and never recover:
        self.window.mark_damage_frame_pending()
        armed = tuple(self.glib.timers)
        for _ in range(5):
            self.window.mark_damage_frame_pending()
        self.assertEqual(tuple(self.glib.timers), armed)

    def test_the_timeout_is_dropped_with_the_window(self):
        self.window.mark_damage_frame_pending()
        self.window.unmanage()
        self.assertFalse(self.glib.timers, "a pending timeout would keep the model alive")
        self.assertAcknowledged(0)


class WaylandSubsurfaceFrameTest(unittest.TestCase):

    def setUp(self):
        self.glib = FakeGLib()
        patcher = patch.object(frame_model, "GLib", self.glib)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.surface = Mock()
        self.display = Mock()
        self.facade = SubsurfaceWindow(320, 240, surface=self.surface, display=self.display)

    def test_a_subsurface_answers_its_own_surface(self):
        # `wlr_surface_send_frame_done` drains the callbacks of the surface it is given,
        # and nothing walks the tree, so the parent cannot answer for the child:
        parent_surface = Mock()
        self.facade.acknowledge_changes()
        self.surface.frame_done.assert_called_once_with()
        self.display.flush_clients.assert_called_once_with()
        parent_surface.frame_done.assert_not_called()

    def test_a_window_source_can_acknowledge_a_subsurface_frame(self):
        # `send_delayed_regions` calls this on every damage it sends, and the facade
        # used to have no `acknowledge_changes` at all - it raised `AttributeError`:
        source = Mock()
        source.window = self.facade
        WindowSource.send_delayed_regions(source, Mock())
        self.surface.frame_done.assert_called_once_with()

    def test_dropping_a_subsurface_cancels_its_frame_timeout(self):
        self.facade.mark_damage_frame_pending()
        self.assertTrue(self.glib.timers)
        self.facade.unmanage()
        self.assertFalse(self.glib.timers, "a pending timeout would keep the facade alive")
        self.assertFalse(self.facade.is_managed())


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

        window.schedule_empty_acknowledgement.side_effect = check_subsurface_updates
        WaylandWindowServer.commit(server, 7, True, (100, 80), (), [subsurface])

        window.schedule_empty_acknowledgement.assert_called_once_with()
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
        window.mark_damage_frame_pending.assert_called_once_with()

    def test_damage_is_marked_before_it_can_be_sent(self):
        # `refresh_window_area` can send the delayed regions synchronously, which
        # acknowledges the frame - so marking it afterwards would never be cleared:
        window = Mock()
        server = self.make_server(window)
        server.refresh_window_area.side_effect = (
            lambda *_args, **_kwargs: window.mark_damage_frame_pending.assert_called_once_with()
        )

        WaylandWindowServer.commit(server, 7, True, (100, 80), ((1, 2, 3, 4),), [])

        self.assertEqual(server.refresh_window_area.call_count, 1)

    def test_an_unmapped_commit_does_not_wait_for_a_frame_it_will_not_get(self):
        window = Mock()
        server = self.make_server(window)

        WaylandWindowServer.commit(server, 7, False, (100, 80), (), [])

        window.mark_damage_frame_pending.assert_not_called()
        window.schedule_empty_acknowledgement.assert_not_called()
        server.refresh_window_area.assert_not_called()

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

    def test_a_subsurface_empty_commit_answers_its_callback(self):
        # the child committed without damaging anything: no damage will come through
        # to answer its frame callback, so the handler has to do it
        window = Mock()
        server = self.make_server(window)
        facade = Mock()
        server.subsurface_facades[2] = facade

        WaylandWindowServer.subsurface_empty_commit(server, 2)

        facade.schedule_empty_acknowledgement.assert_called_once_with()

    def test_a_subsurface_empty_commit_for_an_unknown_child_is_ignored(self):
        window = Mock()
        server = self.make_server(window)
        WaylandWindowServer.subsurface_empty_commit(server, 2)   # must not raise

    def test_subsurface_damage_is_marked_before_it_can_be_sent(self):
        window = Mock()
        server = self.make_server(window)
        facade = Mock()
        server.subsurface_facades[2] = facade
        server.subsurface_info[2] = (7, 0, 0, 5, 6, 5, 6)
        source = Mock()
        server.window_sources.return_value = (source,)
        source.make_subsurface_source.return_value.damage.side_effect = (
            lambda *_args: facade.mark_damage_frame_pending.assert_called_once_with()
        )

        WaylandWindowServer.subsurface_image(server, 2, Mock(), 5, 6, 5, 6)

        source.make_subsurface_source.return_value.damage.assert_called_once()

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

    def test_surface_metadata_updates_the_window(self):
        window = Mock()
        server = self.make_server(window)

        self.assertIn("title", PER_SURFACE_EVENTS)
        self.assertIn("app-id", PER_SURFACE_EVENTS)

        WaylandWindowServer.title(server, 7, "New title")
        WaylandWindowServer.app_id(server, 7, "com.example.Application")

        self.assertEqual(window._updateprop.call_args_list, [
            (("title", "New title"),),
            (("app-id", "com.example.Application"),),
        ])


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
