#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Test GTK iconification state handling without a display server."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from xpra.client.gtk3.window.base import GTKClientWindowBase
from xpra.net.packet_type import WINDOW_UNMAP


class Window:
    set_iconic = GTKClientWindowBase.set_iconic
    update_window_state = GTKClientWindowBase.update_window_state
    schedule_send_iconify = GTKClientWindowBase.schedule_send_iconify
    send_iconify = GTKClientWindowBase.send_iconify
    cancel_send_iconifiy_timer = GTKClientWindowBase.cancel_send_iconifiy_timer
    cleanup = GTKClientWindowBase.cleanup

    def __init__(self):
        self.wid = 7
        self._client = SimpleNamespace(readonly=False)
        self.window_subsystem = SimpleNamespace(server_window_states=("iconified",))
        self._iconified = False
        self._server_iconify_pending = False
        self._override_redirect = False
        self._frozen = False
        self._window_state = {}
        self.window_state_timer = 0
        self.send_iconify_timer = 0
        self.on_realize_cb = {}
        self.timeout_add = Mock(return_value=123)
        self.source_remove = Mock()
        for name in ("iconify", "deiconify", "_unfocus", "send", "emit", "process_map_event",
                     "cancel_window_state_timer", "cancel_moveresize_timer", "cancel_follow_handler",
                     "set_attention_requested"):
            setattr(self, name, Mock())

    def get_subsystem(self, name):
        return self.window_subsystem if name == "window" else None


class IconifyTests(unittest.TestCase):
    def setUp(self):
        self.window = Window()

    def test_server_request_waits_for_gtk_confirmation(self):
        w = self.window
        w.set_iconic(True)
        w.iconify.assert_called_once()
        w.timeout_add.assert_not_called()
        w.update_window_state({"iconified": True})
        w._unfocus.assert_called_once()
        self.assertFalse(w._server_iconify_pending)
        self.assertEqual(w.send_iconify_timer, 123)
        w.send_iconify()
        w.send.assert_called_once_with(WINDOW_UNMAP, 7, True, {})

    def test_repeated_requests_and_events_do_not_resend(self):
        w = self.window
        w.set_iconic(True)
        w.set_iconic(True)
        w.update_window_state({"iconified": True})
        w.update_window_state({"iconified": True})
        w.timeout_add.assert_called_once()
        w.send_iconify()
        w.set_iconic(True)
        w.update_window_state({"iconified": True})
        w.timeout_add.assert_called_once()
        w.iconify.assert_called_once()

    def test_unrelated_event_preserves_pending_confirmation(self):
        w = self.window
        w.set_iconic(True)
        w.update_window_state({})
        self.assertTrue(w._server_iconify_pending)
        w.timeout_add.assert_not_called()

    def test_local_minimize_uses_existing_path(self):
        w = self.window
        w.update_window_state({"iconified": True})
        w._unfocus.assert_called_once()
        w.send_iconify()
        w.send.assert_called_once_with(WINDOW_UNMAP, 7, True, {})

    def test_restore_cancels_delayed_unmap(self):
        w = self.window
        w.set_iconic(True)
        w.update_window_state({"iconified": True})
        w.update_window_state({"iconified": False})
        w.source_remove.assert_called_once_with(123)
        w.process_map_event.assert_called_once()
        w.send_iconify()
        w.send.assert_not_called()

    def test_server_restore_clears_pending_confirmation(self):
        w = self.window
        w.set_iconic(True)
        w.set_iconic(False)
        self.assertFalse(w._server_iconify_pending)
        w.update_window_state({"iconified": False})
        w.send.assert_not_called()
        w.set_iconic(True)
        w.update_window_state({"iconified": True})
        w.set_iconic(False)
        w.source_remove.assert_called_once_with(123)
        self.assertEqual(w.send_iconify_timer, 0)
        w.send_iconify()
        w.send.assert_not_called()

    def test_cleanup_cancels_pending_confirmation_and_timer(self):
        w = self.window
        w.set_iconic(True)
        w.cleanup()
        self.assertFalse(w._server_iconify_pending)
        w._iconified = False
        w.set_iconic(True)
        w.update_window_state({"iconified": True})
        w.cleanup()
        w.source_remove.assert_called_once_with(123)
        self.assertEqual(w.send_iconify_timer, 0)


if __name__ == "__main__":
    unittest.main()
