#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Native read-only clients suppress input and window changes, retaining local shortcuts."""

import unittest
from ctypes import addressof
from types import SimpleNamespace, MethodType
from unittest.mock import Mock, patch

from xpra.os_util import WIN32
from xpra.util.objects import typedict


@unittest.skipUnless(WIN32, "the native client requires MS Windows")
class Win32ReadonlyTest(unittest.TestCase):

    def setUp(self):
        from xpra.client.gui.ui_client_base import UIXpraClient
        from xpra.client.win32.client import XpraWin32Client
        self.client_class = XpraWin32Client
        self.sent = []
        self.pointer = Mock()
        self.client = SimpleNamespace(
            readonly=False, server_readonly=False,
            send=lambda *packet: self.sent.append(packet),
            get_subsystem=lambda name: self.pointer if name == "pointer" else None,
            get_modifiers=lambda: [], get_monitor_position=lambda window: {},
            key_handled_as_shortcut=Mock(return_value=False),
            legacy_server=lambda: False,
            _pointer_data=lambda *args: (10, 20, 1, 2),
        )
        self.client.is_readonly = MethodType(UIXpraClient.is_readonly, self.client)
        self.window = SimpleNamespace(
            client=self.client, wid=7, x=20, y=40, width=200, height=100,
            state_updates={"fullscreen": True}, resize_counter=3,
            pop_client_properties=lambda: {},
        )

    def test_readonly_window_changes(self):
        for policy in ("readonly", "server_readonly"):
            setattr(self.client, policy, True)
            for name in ("window_minimized_event", "window_maximized_event", "send_configure"):
                self.window.state_updates = {"fullscreen": True}
                getattr(self.client_class, name)(self.client, self.window)
            self.assertEqual(self.sent, [])
            self.assertEqual(self.window.state_updates, {})
            setattr(self.client, policy, False)

    def test_readonly_input(self):
        self.client.server_readonly = True
        self.client_class.window_mouse_moved_event(self.client, self.window, 1, 2, (), ())
        self.client_class.window_wheel_event(self.client, self.window, 1, 2, True, (), 120)
        self.client_class.window_key_event(self.client, self.window, "a", True, 65, "a", 30, False)
        self.assertEqual(self.sent, [])
        self.pointer.assert_not_called()
        self.pointer.send_mouse_position.assert_not_called()
        self.pointer.send_wheel_delta.assert_not_called()
        self.client.key_handled_as_shortcut.assert_called_once()

    def test_readonly_button_release_reaches_pointer_policy(self):
        # The pointer subsystem must release buttons pressed before the policy changed.
        self.client.readonly = True
        self.client_class.window_mouse_clicked_event(self.client, self.window, 1, False, 1, 2, (), ())
        self.pointer.send_button.assert_called_once()
        self.assertFalse(self.pointer.send_button.call_args.args[3])

    def test_writable_configure(self):
        self.client_class.send_configure(self.client, self.window)
        self.assertEqual(self.sent, [("window-configure", 7, {
            "state": {"fullscreen": True}, "geometry": (20, 40, 200, 100),
            "resize-counter": 3, "raw-position": (20, 40),
        })])
        self.assertEqual(self.window.state_updates, {})

    def test_writable_keyboard_compatibility(self):
        for legacy in (False, True):
            self.client.legacy_server = lambda: legacy
            with patch("xpra.client.win32.client.get_native_modifiers", return_value={}):
                self.client_class.window_key_event(self.client, self.window, "a", True, 65, "a", 30, False)
            packet = self.sent.pop()
            self.assertEqual(packet[0], "key-action" if legacy else "keyboard-event")
            self.assertEqual(packet[1:4], (7, "a", True))

    def test_native_fixed_size(self):
        from xpra.client.win32.window import ClientWindow
        from xpra.platform.win32.common import MINMAXINFO
        window = self.window
        window.is_readonly = MethodType(ClientWindow.is_readonly, window)
        window.style = 0
        window.size_constraints = typedict()
        window.max_window_size = (1000, 1000)
        window._requested_size = (300, 200)
        self.client.readonly = True
        info = MINMAXINFO()
        with patch("xpra.client.win32.window.GetWindowLongW", return_value=0), \
                patch("xpra.client.win32.window.system_geometry", return_value=(0, 0, 16, 39)):
            ClientWindow.apply_size_constraints(window, 1, addressof(info))
        self.assertEqual((info.ptMinTrackSize.x, info.ptMinTrackSize.y), (316, 239))
        self.assertEqual((info.ptMaxTrackSize.x, info.ptMaxTrackSize.y), (316, 239))
        self.assertEqual((info.ptMaxSize.x, info.ptMaxSize.y), (316, 239))


if __name__ == "__main__":
    unittest.main()
