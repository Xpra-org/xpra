#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 kogeler
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gc
import unittest

from xpra.common import noop
from xpra.net.common import BACKWARDS_COMPATIBLE, Packet
from xpra.os_util import gi_import
from xpra.util.objects import typedict
from unit.process_test_util import DisplayContext


class PopupModalTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        display = DisplayContext()
        cls.addClassCleanup(display.__exit__)
        display.__enter__()
        Gtk = gi_import("Gtk")
        cls.addClassCleanup(cls.finish_gtk_cleanup)
        from xpra.client.subsystem.window.manager import WindowManagerClient

        class NativeWindow(Gtk.Window):
            def __init__(self, geometry, metadata, override_redirect):
                window_type = Gtk.WindowType.POPUP if override_redirect else Gtk.WindowType.TOPLEVEL
                super().__init__(type=window_type)
                self._metadata = metadata
                self._override_redirect = override_redirect
                self._pos = geometry[:2]
                self.set_default_size(*geometry[2:])
                self.set_modal(metadata.boolget("modal"))
                self.realize()

            def is_OR(self):
                return self._override_redirect

            def is_tray(self):
                return self._metadata.boolget("tray")

            @staticmethod
            def sp(x, y):
                return x, y

        class PopupManager(WindowManagerClient):
            _ui_event = noop

            @staticmethod
            def destroy_window(_wid, window):
                window.destroy()

            def make_new_window(self, wid, geom, backing_size, metadata, override_redirect, client_properties):
                window = NativeWindow(geom, metadata, override_redirect)
                window.backing_size = backing_size
                window.client_properties = client_properties
                self._id_to_window[wid] = window
                self._window_to_id[window] = wid
                return window

        cls.manager_class = PopupManager

    @staticmethod
    def finish_gtk_cleanup():
        Gtk = gi_import("Gtk")
        GLib = gi_import("GLib")
        for window in Gtk.Window.list_toplevels():
            window.destroy()
        context = GLib.main_context_default()

        def drain():
            for _ in range(100):
                if not context.pending():
                    break
                context.iteration(False)

        # Failed assertions can retain GTK cycles until after per-test cleanup.
        # Release their native state while the display connection is still open.
        drain()
        gc.collect()
        drain()

    def setUp(self):
        self.manager = self.manager_class()
        self.addCleanup(self.destroy_windows)

    def destroy_windows(self):
        for window in self.manager._id_to_window.values():
            window.destroy()
        self.manager._id_to_window.clear()
        self.manager._window_to_id.clear()

    def register_window(self, wid, *, modal=False, override_redirect=False, tray=False):
        # Seed native state without the create handler, so the close regression
        # remains independently observable on production-clean source.
        return self.manager.make_new_window(
            wid, (100, 200, 300, 200), (300, 200),
            typedict({"modal": modal, "tray": tray}), override_redirect, typedict(),
        )

    def create_popup(self, wid, **metadata):
        self.manager._process_window_create(Packet(
            "window-create", wid, 10, 20, 120, 80,
            {"override-redirect": True, **metadata}, {"workspace": 2},
        ))
        return self.manager.get_window(wid)

    def test_new_popup_preserves_the_incoming_id(self):
        for kind in ({}, {"modal": True}, {"override_redirect": True}, {"tray": True}):
            with self.subTest(existing=kind):
                self.destroy_windows()
                existing = self.register_window(3, **kind)
                popup = self.create_popup(4)
                self.assertEqual(set(self.manager._id_to_window), {3, 4})
                self.assertIs(self.manager.get_window(3), existing)
                self.assertEqual(self.manager._window_to_id[popup], 4)
                self.assertTrue(popup.is_OR())
                self.assertIsNotNone(popup.get_window())
                self.assertFalse(existing.get_modal())
                self.assertEqual(popup.backing_size, (120, 80))
                self.assertEqual(popup.client_properties, {"workspace": 2})

    def test_first_popup_and_disabled_modal_policy(self):
        popup = self.create_popup(4)
        self.assertIsNotNone(popup)
        self.manager._process_window_destroy(Packet("window-destroy", 4))
        parent = self.register_window(3, modal=True)
        self.manager.modal_windows = False
        self.assertIsNotNone(self.create_popup(4))
        self.assertTrue(parent.get_modal())
        self.manager._process_window_destroy(Packet("window-destroy", 4))
        self.assertTrue(parent.get_modal())

    def test_relative_geometry_keeps_the_parent_and_popup_ids(self):
        parent = self.register_window(3)
        popup = self.create_popup(7, parent=3, **{"relative-position": (12, 23)})
        self.assertEqual(popup._pos, (112, 223))
        self.assertIs(self.manager.get_window(3), parent)
        self.assertEqual(self.manager._window_to_id[popup], 7)

    def test_real_duplicate_id_is_still_rejected(self):
        existing = self.register_window(3)
        with self.assertRaisesRegex(ValueError, "we already have a window 0x3"):
            self.create_popup(3)
        self.assertEqual(self.manager._id_to_window, {3: existing})
        self.assertEqual(self.manager._window_to_id, {existing: 3})

    @unittest.skipUnless(BACKWARDS_COMPATIBLE, "legacy packet compatibility is disabled")
    def test_legacy_override_redirect_packet(self):
        parent = self.register_window(3, modal=True)
        self.manager._process_new_override_redirect(Packet(
            "new-override-redirect", 4, 10, 20, 120, 80, {},
        ))
        popup = self.manager.get_window(4)
        self.assertIsNotNone(popup)
        self.assertTrue(popup.is_OR())
        self.assertFalse(parent.get_modal())

    def test_close_restores_the_parent_not_the_closing_popup(self):
        parent = self.register_window(3, modal=True)
        parent.set_modal(False)
        unrelated = self.register_window(9)
        tray = self.register_window(10, tray=True, modal=True)
        tray.set_modal(False)
        popup = self.register_window(4, override_redirect=True)
        modal_changes = []
        popup.connect("notify::modal", lambda window, _prop: modal_changes.append(window.get_modal()))
        self.manager._process_window_destroy(Packet("window-destroy", 4))
        self.assertTrue(parent.get_modal())
        self.assertFalse(unrelated.get_modal())
        self.assertFalse(tray.get_modal())
        self.assertEqual(modal_changes, [])
        self.assertNotIn(4, self.manager._id_to_window)
        self.assertNotIn(popup, self.manager._window_to_id)

    def test_nested_popups_restore_modal_windows_only_after_the_last_close(self):
        parents = [self.register_window(wid, modal=True) for wid in (3, 8)]
        self.create_popup(4)
        self.create_popup(5)
        self.assertTrue(all(not parent.get_modal() for parent in parents))
        self.manager._process_window_destroy(Packet("window-destroy", 4))
        self.assertTrue(all(not parent.get_modal() for parent in parents))
        self.assertEqual(set(self.manager._id_to_window), {3, 5, 8})
        self.manager._process_window_destroy(Packet("window-destroy", 5))
        self.assertTrue(all(parent.get_modal() for parent in parents))
        self.assertEqual(set(self.manager._id_to_window), {3, 8})


def main():
    unittest.main()


if __name__ == "__main__":
    main()
