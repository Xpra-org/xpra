#!/usr/bin/env python3
# This file is part of Xpra.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Exercise Windows session callbacks without requiring native Windows libraries."""

import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, call, patch

import xpra


class SessionEventsTest(unittest.TestCase):

    def setUp(self):
        self.pending = []
        self.locked = False
        constants = SimpleNamespace(CTRL_C_EVENT=0, CTRL_LOGOFF_EVENT=5, CTRL_BREAK_EVENT=1,
                                    CTRL_SHUTDOWN_EVENT=6, CTRL_CLOSE_EVENT=2)
        platform = ModuleType("xpra.platform.win32")
        platform.constants = constants
        platform.setup_console_event_listener = Mock()
        events = ModuleType("xpra.platform.win32.events")
        events.KNOWN_EVENTS = {}
        events.Win32Eventlistener = object
        events.get_win32_event_listener = Mock()
        gui = ModuleType("xpra.platform.win32.gui")
        gui.WM_WTSSESSION_CHANGE = 0x2B1
        gui.WTS_SESSION_EVENTS = {}
        gui.WTS_SESSION_LOGOFF = 6
        gui.WTS_SESSION_LOGON = 5
        gui.WTS_SESSION_LOCK = 7
        gui.WTS_SESSION_UNLOCK = 8
        gui.init_session_locked = Mock()
        gui.set_session_locked = self.set_locked
        gui.is_session_locked = lambda: self.locked
        modules = {platform.__name__: platform, events.__name__: events, gui.__name__: gui}
        filename = Path(xpra.__file__).parent / "platform" / "win32" / "window_events.py"
        spec = importlib.util.spec_from_file_location("xpra_win32_session_events_test", filename)
        module = importlib.util.module_from_spec(spec)
        glib = SimpleNamespace(idle_add=self.pending.append)
        with patch.dict(sys.modules, modules), patch("xpra.os_util.gi_import", return_value=glib):
            spec.loader.exec_module(module)
        self.window = Mock(spec=["refresh_slowly", "show_locked_windows", "send_refresh_all", "freeze", "unfreeze"])
        self.watcher = module.Win32ClientEventsWatcher(self.window)

    def set_locked(self, locked):
        self.locked = locked

    def drain(self):
        pending = list(self.pending)
        self.pending.clear()
        for handler in pending:
            handler()

    def test_lock_records_state_before_deferred_refresh_pause(self):
        self.watcher.session_change_event(7, 1)
        self.assertTrue(self.locked)
        self.assertEqual(self.window.mock_calls, [])
        self.drain()
        self.assertEqual(self.window.mock_calls, [call.refresh_slowly()])

    def test_unlock_shows_deferred_windows_and_refreshes_without_unfreezing(self):
        self.locked = True
        self.watcher.session_change_event(8, 1)
        self.assertFalse(self.locked)
        self.assertEqual(self.window.mock_calls, [])
        self.drain()
        self.assertEqual(self.window.mock_calls, [call.show_locked_windows(), call.send_refresh_all()])

    def test_lock_unlock_does_not_minimize_or_restore_existing_windows(self):
        self.watcher.session_change_event(7, 1)
        self.drain()
        self.watcher.session_change_event(8, 1)
        self.drain()
        self.window.freeze.assert_not_called()
        self.window.unfreeze.assert_not_called()
        self.assertEqual(self.window.mock_calls,
                         [call.refresh_slowly(), call.show_locked_windows(), call.send_refresh_all()])

    def test_stale_lock_callback_does_not_pause_after_unlock(self):
        self.watcher.session_change_event(7, 1)
        self.watcher.session_change_event(8, 1)
        self.drain()
        self.window.refresh_slowly.assert_not_called()
        self.window.send_refresh_all.assert_called_once_with()

    def test_stale_unlock_callback_does_not_show_windows_after_relock(self):
        self.watcher.session_change_event(8, 1)
        self.watcher.session_change_event(7, 1)
        self.drain()
        self.window.show_locked_windows.assert_not_called()
        self.window.send_refresh_all.assert_not_called()
        self.window.refresh_slowly.assert_called_once_with()

    def test_logoff_still_freezes(self):
        self.watcher.session_change_event(6, 1)
        self.assertTrue(self.locked)
        self.assertEqual(self.window.mock_calls, [])
        self.drain()
        self.assertEqual(self.window.mock_calls, [call.freeze()])

    def test_logon_still_unfreezes(self):
        self.locked = True
        self.watcher.session_change_event(5, 1)
        self.assertFalse(self.locked)
        self.drain()
        self.assertEqual(self.window.mock_calls, [call.unfreeze()])

    def test_other_session_events_do_not_change_state_or_queue_callbacks(self):
        for locked in (False, True):
            with self.subTest(locked=locked):
                self.locked = locked
                self.watcher.session_change_event(99, 1)
                self.assertEqual(self.locked, locked)
                self.assertEqual(self.pending, [])
        self.assertEqual(self.window.mock_calls, [])


def main():
    unittest.main()


if __name__ == "__main__":
    main()
