#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Tests for the handling of `AltGr` in the native win32 client:
Windows sends it as a fake left `Control` followed by the right `Alt` key,
the fake `Control` must not reach the server and `AltGr` must be sent as `ISO_Level3_Shift`.
These tests are skipped on non-Windows platforms.
"""

import sys
import unittest

WIN32 = sys.platform == "win32"

VK_CONTROL = 0x11
VK_MENU = 0x12
VK_Q = 0x51
WM_KEYDOWN = 0x100
WM_KEYUP = 0x101
WM_SYSKEYDOWN = 0x104
WM_SYSKEYUP = 0x105
SCANCODE = {
    VK_CONTROL: 0x1D,
    VK_MENU: 0x38,
    VK_Q: 0x10,
}


def lparam(vk: int, down=True, extended=False, repeat=False) -> int:
    value = 1 | (SCANCODE[vk] << 16)
    if extended:
        value |= 1 << 24
    if repeat or not down:
        # the previous key state:
        value |= 1 << 30
    if not down:
        # the transition state:
        value |= 1 << 31
    return value


def key_message(message: int, vk: int, extended=False, time=1000, repeat=False):
    from xpra.client.win32.altgr import KeyMessage
    down = message in (WM_KEYDOWN, WM_SYSKEYDOWN)
    return KeyMessage(message, vk, lparam(vk, down, extended, repeat), time)


@unittest.skipUnless(WIN32, "the win32 client is only available on MS Windows")
class AltGrClassificationTest(unittest.TestCase):

    def setUp(self):
        from xpra.client.win32 import altgr
        altgr.altgr_layouts.clear()

    def is_fake(self, key, other) -> bool:
        from xpra.client.win32.altgr import is_altgr_fake_control
        return is_altgr_fake_control(key, other)

    def test_press_release_repeat(self):
        for control, alt, repeat in (
            (WM_KEYDOWN, WM_KEYDOWN, False),
            (WM_KEYDOWN, WM_KEYDOWN, True),
            (WM_KEYUP, WM_KEYUP, False),
            # the right `Alt` may be reported as a system key:
            (WM_KEYDOWN, WM_SYSKEYDOWN, False),
            (WM_KEYUP, WM_SYSKEYUP, False),
        ):
            fake = key_message(control, VK_CONTROL, repeat=repeat)
            alt_r = key_message(alt, VK_MENU, extended=True, repeat=repeat)
            self.assertTrue(self.is_fake(fake, alt_r))

    def test_real_control(self):
        alt_r = key_message(WM_KEYDOWN, VK_MENU, extended=True)
        # no right `Alt` key next to it:
        self.assertFalse(self.is_fake(key_message(WM_KEYDOWN, VK_CONTROL), None))
        # pressed at a different time:
        self.assertFalse(self.is_fake(key_message(WM_KEYDOWN, VK_CONTROL, time=990), alt_r))
        # the right `Control` key:
        self.assertFalse(self.is_fake(key_message(WM_KEYDOWN, VK_CONTROL, extended=True), alt_r))
        # released while the right `Alt` is pressed:
        self.assertFalse(self.is_fake(key_message(WM_KEYUP, VK_CONTROL), alt_r))
        # next to the left `Alt` key, or another key:
        self.assertFalse(self.is_fake(key_message(WM_KEYDOWN, VK_CONTROL), key_message(WM_SYSKEYDOWN, VK_MENU)))
        self.assertFalse(self.is_fake(key_message(WM_KEYDOWN, VK_CONTROL), key_message(WM_KEYDOWN, VK_Q)))
        # not a `Control` key at all:
        self.assertFalse(self.is_fake(key_message(WM_KEYDOWN, VK_Q), alt_r))

    def test_alt_r_keyname(self):
        from xpra.client.win32.altgr import add_altgr_layout, get_alt_r_keyname
        us = 0x04090409
        de = 0x04070407
        add_altgr_layout(de)
        self.assertEqual(get_alt_r_keyname(us), "Alt_R")
        self.assertEqual(get_alt_r_keyname(de), "ISO_Level3_Shift")


class FakeWindowManager:
    def __init__(self):
        self.windows = {}

    def get_window(self, wid: int):
        return self.windows.get(wid)


class FakeClient:

    def __init__(self):
        self.window_manager = FakeWindowManager()
        self.subsystems = {"window": self.window_manager}

    def get_subsystem(self, name: str):
        return self.subsystems.get(name)


@unittest.skipUnless(WIN32, "the win32 client is only available on MS Windows")
class WindowAltGrTest(unittest.TestCase):
    """
    feeds key messages to a real window and records the key events it emits
    """

    def setUp(self):
        from xpra.util.objects import typedict
        from xpra.client.win32 import altgr
        from xpra.client.win32.window import ClientWindow
        altgr.altgr_layouts.clear()
        self.client = FakeClient()
        self.window = ClientWindow(self.client, None, 1, (100, 100, 200, 100), (200, 100), typedict(),
                                   False, {}, None, (4096, 4096), 32, None)
        self.window.create()
        self.client.window_manager.windows[1] = self.window
        self.keys = []
        self.window.connect("key", self.key_event)

    def tearDown(self):
        from xpra.client.win32 import altgr
        self.window.destroy()
        # this is normally done from the main loop, which we don't run:
        self.window.cleanup_class()
        altgr.altgr_layouts.clear()

    def key_event(self, _window, keyname: str, pressed: bool, *_args) -> None:
        self.keys.append((keyname, pressed))

    def send(self, messages, time=1000) -> None:
        """
        calls the window procedure for each message, as if they were all
        in the queue with the same message `time`
        """
        from unittest.mock import patch
        from xpra.client.win32 import window as window_module
        queue = [key_message(message, vk, extended, time) for message, vk, extended in messages]
        while queue:
            msg = queue.pop(0)
            with (
                patch.object(window_module, "GetMessageTime", return_value=msg.time),
                patch.object(window_module, "peek_key_message", return_value=queue[0] if queue else None),
            ):
                self.window.wnd_proc_cb(self.window.hwnd, msg.message, msg.vk_code, msg.lparam)

    def test_altgr(self):
        self.send(((WM_KEYDOWN, VK_CONTROL, False), (WM_KEYDOWN, VK_MENU, True)), time=1000)
        # autorepeat:
        self.send(((WM_KEYDOWN, VK_CONTROL, False), (WM_KEYDOWN, VK_MENU, True)), time=1500)
        self.send(((WM_KEYUP, VK_CONTROL, False), (WM_SYSKEYUP, VK_MENU, True)), time=2000)
        self.assertEqual(self.keys, [
            ("ISO_Level3_Shift", True),
            ("ISO_Level3_Shift", True),
            ("ISO_Level3_Shift", False),
        ])

    def test_altgr_release_reversed(self):
        # the fake `Control` is also recognized after the right `Alt` key:
        self.send(((WM_KEYDOWN, VK_CONTROL, False), (WM_KEYDOWN, VK_MENU, True)), time=1000)
        self.send(((WM_SYSKEYUP, VK_MENU, True), (WM_KEYUP, VK_CONTROL, False)), time=2000)
        self.assertEqual(self.keys, [
            ("ISO_Level3_Shift", True),
            ("ISO_Level3_Shift", False),
        ])

    def test_real_control_and_alt(self):
        # a real `Control` then the right `Alt` key on a layout without `AltGr` (ie: US):
        self.send(((WM_KEYDOWN, VK_CONTROL, False), ), time=1000)
        self.send(((WM_KEYDOWN, VK_MENU, True), ), time=1100)
        self.send(((WM_KEYUP, VK_MENU, True), ), time=1200)
        self.send(((WM_KEYUP, VK_CONTROL, False), ), time=1300)
        self.assertEqual(self.keys, [
            ("Control_L", True),
            ("Alt_R", True),
            ("Alt_R", False),
            ("Control_L", False),
        ])

    def test_posted_messages(self):
        # the same thing through the real message queue, using `PeekMessageW` and `GetMessageTime`:
        from ctypes import byref
        from ctypes.wintypes import MSG, HWND, WPARAM, LPARAM
        import win32con
        from xpra.platform.win32.common import PostMessageA, PeekMessageW, DispatchMessageW
        hwnd = self.window.hwnd
        for message, vk, extended in (
            (WM_KEYDOWN, VK_CONTROL, False),
            (WM_KEYDOWN, VK_MENU, True),
            (WM_KEYUP, VK_CONTROL, False),
            (WM_SYSKEYUP, VK_MENU, True),
        ):
            down = message == WM_KEYDOWN
            self.assertTrue(PostMessageA(HWND(hwnd), message, WPARAM(vk), LPARAM(lparam(vk, down, extended))))
        msg = MSG()
        times = []
        while PeekMessageW(byref(msg), hwnd, win32con.WM_KEYFIRST, win32con.WM_KEYLAST, win32con.PM_REMOVE):
            times.append(msg.time)
            DispatchMessageW(byref(msg))
        if times[0] != times[1] or times[2] != times[3]:
            self.skipTest(f"the messages were posted at different times: {times}")
        self.assertEqual(self.keys, [
            ("ISO_Level3_Shift", True),
            ("ISO_Level3_Shift", False),
        ])


def main():
    unittest.main()


if __name__ == "__main__":
    main()
