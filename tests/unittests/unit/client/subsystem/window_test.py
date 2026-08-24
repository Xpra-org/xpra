#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock, patch

from xpra.os_util import WIN32
from xpra.net.packet_type import WINDOW_STACKING
from xpra.util.objects import AdHocStruct
from unit.process_test_util import DisplayContext
from unit.client.subsystem.clientmixintest_util import ClientMixinTest


class WindowManagerTest(ClientMixinTest):

    @unittest.skipUnless(WIN32, "win32 only")
    def test_win32_window_stacking(self):
        from xpra.platform.win32 import constants as win32con
        from xpra.platform.win32.window_stacking import Win32WindowStackingWatcher

        def window(hwnd: int, tray=False):
            model = Mock()
            model.is_tray.return_value = tray
            model.get_window_handle.return_value = hwnd
            return model

        # a tray has no window handle at all: `get_window_handle` must not be called on it
        tray = Mock()
        tray.is_tray.return_value = True
        del tray.get_window_handle

        window_client = AdHocStruct()
        window_client._id_to_window = {
            1: window(0x101),
            2: window(0x102),
            3: window(0),
            4: tray,
        }
        window_client.server_window_stacking = True
        window_client.send_window_stacking = Mock()
        window_client.client = AdHocStruct()
        window_client.client.after_handshake = Mock()

        watcher = Win32WindowStackingWatcher(window_client)
        watcher.setup()
        window_client.client.after_handshake.assert_called_once_with(watcher.do_setup)

        prefix = "xpra.platform.win32.window_stacking."
        with patch(prefix + "get_hwnd_stacking", return_value=(0x999, 0x102, 0x101)) as get_hwnd_stacking:
            with patch(prefix + "SetWinEventHook", return_value=0x1234) as set_hook:
                watcher.do_setup()
        # a single hook covers `EVENT_OBJECT_CREATE` .. `EVENT_OBJECT_REORDER`:
        set_hook.assert_called_once()
        self.assertEqual(set_hook.call_args[0][:2], (win32con.EVENT_OBJECT_CREATE, win32con.EVENT_OBJECT_REORDER))
        # only the windows which do have a handle are looked up:
        self.assertEqual(get_hwnd_stacking.call_args[0][0], {0x101: 1, 0x102: 2})
        # `EnumWindows` returns the topmost window first, the packet is bottom-to-top:
        window_client.send_window_stacking.assert_called_once_with((1, 2))

        # events for the controls within a window must not trigger an update:
        watcher.win_event(0, win32con.EVENT_OBJECT_SHOW, 0x101, win32con.OBJID_CLIENT, 9, 0, 0)
        self.assertFalse(watcher.stacking_timer)
        watcher.win_event(0, win32con.EVENT_OBJECT_SHOW, 0x101, win32con.OBJID_CARET, win32con.CHILDID_SELF, 0, 0)
        self.assertFalse(watcher.stacking_timer)
        # whole windows appearing, disappearing or moving in the z-order do:
        watcher.win_event(0, win32con.EVENT_OBJECT_HIDE, 0x101, win32con.OBJID_WINDOW, win32con.CHILDID_SELF, 0, 0)
        self.assertTrue(watcher.stacking_timer)
        watcher.cancel_stacking_timer()
        # reorders are reported against the desktop window using `OBJID_CLIENT`:
        watcher.win_event(0, win32con.EVENT_OBJECT_REORDER, 0x10010, win32con.OBJID_CLIENT, win32con.CHILDID_SELF, 0, 0)
        self.assertTrue(watcher.stacking_timer)

        with patch(prefix + "UnhookWinEvent") as unhook:
            watcher.cleanup()
        unhook.assert_called_once_with(0x1234)
        self.assertFalse(watcher.stacking_timer)
        self.assertIsNone(watcher.hook)
        # the ctypes callback must outlive the hook: events queued before
        # `UnhookWinEvent` can still be delivered
        self.assertIsNotNone(watcher.callback)

    def test_windowmanager(self):
        with DisplayContext():
            from xpra.client.subsystem.window import WindowClient
            # `get_mouse_position` delegates to the owning client
            # (`WindowPointer.get_mouse_position`), and the test harness
            # provides it as the client stand-in:
            opts = AdHocStruct()
            opts.system_tray = True
            opts.cursors = True
            opts.bell = True
            opts.input_devices = True
            opts.auto_refresh_delay = 0
            opts.min_size = "100x100"
            opts.max_size = "2000x2000"
            opts.pixel_depth = 24
            opts.windows = True
            opts.sharing = "no"
            opts.window_close = "forward"
            opts.modal_windows = True
            opts.border = "red"
            opts.tray_icon = "yes"
            self._test_mixin_class(WindowClient, opts, {"window": {"stacking": True}})
            self.mixin.send_window_stacking((3, 1, 3, 2))
            self.verify_packet(-1, (WINDOW_STACKING, [3, 1, 2]))
            packet_count = len(self.packets)
            self.mixin.send_window_stacking((3, 1, 2))
            self.assertEqual(len(self.packets), packet_count)
            self.mixin.server_window_stacking = False
            self.mixin.send_window_stacking((2, 1))
            self.assertEqual(len(self.packets), packet_count)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
