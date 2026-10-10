#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Test GTK iconification state handling without a display server."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call

from xpra.client.gtk3.window.base import GTKClientWindowBase, Gdk
from xpra.net.packet_type import WINDOW_UNMAP


class Window:
    set_iconic = GTKClientWindowBase.set_iconic
    update_window_state = GTKClientWindowBase.update_window_state
    schedule_send_iconify = GTKClientWindowBase.schedule_send_iconify
    send_iconify = GTKClientWindowBase.send_iconify
    cancel_send_iconifiy_timer = GTKClientWindowBase.cancel_send_iconifiy_timer
    cancel_deiconify_timer = GTKClientWindowBase.cancel_deiconify_timer
    verify_deiconified = GTKClientWindowBase.verify_deiconified
    do_unmap_event = GTKClientWindowBase.do_unmap_event
    cleanup = GTKClientWindowBase.cleanup

    def __init__(self):
        self.wid = 7
        self._client = SimpleNamespace(readonly=False, server_window_states=("iconified",), server_ping_latency=[])
        self._iconified = False
        self._override_redirect = False
        self._frozen = False
        self._window_state = {}
        self.window_state_timer = 0
        self.send_iconify_timer = 0
        self.deiconify_timer = 0
        self._remapping = False
        self.on_realize_cb = {}
        self.timeout_add = Mock(side_effect=lambda _delay, fn: 456 if fn == self.verify_deiconified else 123)
        self.source_remove = Mock()
        self.gdk_window = Mock()
        self.gdk_window.get_state.return_value = Gdk.WindowState.ICONIFIED
        self.focus_on_map = True
        for name in ("iconify", "deiconify", "_unfocus", "send", "emit", "process_map_event",
                     "cancel_window_state_timer", "cancel_moveresize_timer", "cancel_follow_handler"):
            setattr(self, name, Mock())

    def get_window(self):
        return self.gdk_window

    def get_focus_on_map(self) -> bool:
        return self.focus_on_map

    def set_focus_on_map(self, focus_on_map: bool) -> None:
        self.gdk_window.focus_on_map_changes.append(focus_on_map)
        self.focus_on_map = focus_on_map


class IconifyTests(unittest.TestCase):
    def setUp(self):
        self.window = Window()

    def test_local_minimize_uses_existing_path(self):
        w = self.window
        w.update_window_state({"iconified": True})
        w._unfocus.assert_called_once()
        w.send_iconify()
        w.send.assert_called_once_with(WINDOW_UNMAP, 7, True, {})

    def test_restore_cancels_delayed_unmap(self):
        w = self.window
        w.update_window_state({"iconified": True})
        w.update_window_state({"iconified": False})
        w.source_remove.assert_called_once_with(123)
        w.process_map_event.assert_called_once()
        w.send_iconify()
        w.send.assert_not_called()

    def test_server_restore_cancels_delayed_unmap(self):
        w = self.window
        w.set_iconic(True)
        w.set_iconic(False)
        w.update_window_state({"iconified": False})
        w.send.assert_not_called()
        w.update_window_state({"iconified": True})
        w.set_iconic(False)
        # (456 is the deiconify verification timer from the first restore)
        self.assertEqual(w.source_remove.call_args_list, [call(456), call(123)])
        self.assertEqual(w.send_iconify_timer, 0)
        w.send_iconify()
        w.send.assert_not_called()

    def test_deiconify_ignored_by_the_window_manager(self):
        # ie: muffin ignores deiconify requests, so the window is re-mapped instead
        w = self.window
        w.gdk_window.focus_on_map_changes = []
        w.update_window_state({"iconified": True})
        w.set_iconic(False)
        w.deiconify.assert_called_once()
        self.assertEqual(w.deiconify_timer, 456)
        w.verify_deiconified()
        self.assertEqual(w.deiconify_timer, 0)
        w.gdk_window.withdraw.assert_called_once()
        w.gdk_window.show.assert_called_once()
        # without stealing the focus:
        self.assertEqual(w.gdk_window.focus_on_map_changes, [False, True])
        # and without telling the server that the window was unmapped:
        self.assertTrue(w._remapping)
        w.do_unmap_event(None)
        w.send.assert_not_called()

    def test_deiconify_honoured_by_the_window_manager(self):
        w = self.window
        w.set_iconic(True)
        w.set_iconic(False)
        w.gdk_window.get_state.return_value = 0
        w.verify_deiconified()
        w.gdk_window.withdraw.assert_not_called()
        # iconified again before the verification:
        w.set_iconic(False)
        w._iconified = True
        w.set_iconic(True)
        self.assertEqual(w.deiconify_timer, 0)
        w.gdk_window.get_state.return_value = Gdk.WindowState.ICONIFIED
        w.verify_deiconified()
        w.gdk_window.withdraw.assert_not_called()

    def test_cleanup_cancels_timers(self):
        w = self.window
        w.update_window_state({"iconified": True})
        w.cleanup()
        w.source_remove.assert_called_once_with(123)
        self.assertEqual(w.send_iconify_timer, 0)

        w.source_remove.reset_mock()
        w.set_iconic(False)
        self.assertEqual(w.deiconify_timer, 456)
        w.cleanup()
        w.source_remove.assert_called_once_with(456)
        self.assertEqual(w.deiconify_timer, 0)


if __name__ == "__main__":
    unittest.main()
