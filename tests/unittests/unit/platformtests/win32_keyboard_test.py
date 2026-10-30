#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Tests for the keys injected by the win32 server:
modifier-only chords must not reach Windows, as they switch the input language or keyboard layout,
and clearing the keys pressed must release them for the whole system.
The key events are recorded instead of being injected.
Also the virtual keys that the client key names map to.
These tests are skipped on non-Windows platforms.
"""

import sys
import unittest
from unittest.mock import patch

WIN32 = sys.platform == "win32"

VK_SHIFT = 0x10
VK_LSHIFT = 0xA0
VK_LCONTROL = 0xA2
VK_LMENU = 0xA4
VK_C = 0x43
VK_D = 0x44
MASK = 0xE8


@unittest.skipUnless(WIN32, "the win32 keyboard is only available on MS Windows")
class InjectedKeysTest(unittest.TestCase):

    def setUp(self):
        from xpra.platform.win32 import keyboard
        self.keyboard = keyboard
        self.events: list[tuple[int, bool]] = []

        def keybd_event(vk: int, _scancode: int, flags: int, _extra: int) -> None:
            self.events.append((vk, not flags & 2))

        self.patches = (
            patch.object(keyboard, "keybd_event", keybd_event),
            patch.object(keyboard, "injected_modifiers", keyboard.InjectedModifiers()),
        )
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()

    def inject(self, *events: tuple[int, bool]) -> None:
        for vk, press in events:
            self.keyboard.fake_key(vk, press)

    def test_alt_shift_masked(self):
        # the events left over by the `Alt+Shift+Escape` client shortcut:
        self.inject((VK_LSHIFT, True), (VK_LMENU, True), (VK_LMENU, False), (VK_LSHIFT, False))
        self.assertEqual(self.events, [
            (VK_LSHIFT, True), (VK_LMENU, True),
            (MASK, True), (MASK, False),
            (VK_LMENU, False), (VK_LSHIFT, False),
        ])
        self.assertFalse(self.keyboard.injected_modifiers.held)

    def test_duplicate_release(self):
        # `make_keymask_match` may release a modifier before its own key event does:
        self.inject((VK_LSHIFT, True), (VK_LMENU, True), (VK_LMENU, False), (VK_LSHIFT, False), (VK_LSHIFT, False))
        self.assertEqual(self.events.count((MASK, True)), 1)

    def test_chord_with_key(self):
        # ie: `Alt+Shift+D`, the key already cancels the hotkey
        self.inject((VK_LSHIFT, True), (VK_LMENU, True), (VK_D, True), (VK_D, False),
                    (VK_LMENU, False), (VK_LSHIFT, False))
        self.assertNotIn((MASK, True), self.events)

    def test_modifier_after_key(self):
        self.inject((VK_LSHIFT, True), (VK_D, True), (VK_D, False), (VK_LMENU, True),
                    (VK_LMENU, False), (VK_LSHIFT, False))
        self.assertIn((MASK, True), self.events)

    def test_single_modifier(self):
        self.inject((VK_LMENU, True), (VK_LMENU, False))
        self.assertEqual(self.events, [(VK_LMENU, True), (VK_LMENU, False)])

    def test_generic_vk(self):
        self.inject((VK_SHIFT, True), (VK_LSHIFT, False))
        self.assertFalse(self.keyboard.injected_modifiers.held)

    def test_mask_disabled(self):
        with patch.object(self.keyboard, "MASK_KEY", 0):
            self.inject((VK_LSHIFT, True), (VK_LMENU, True), (VK_LMENU, False), (VK_LSHIFT, False))
        self.assertNotIn((MASK, True), self.events)

    def test_clear_keys_pressed(self):
        # `Control_L` pressed by `make_keymask_match`, `c` by a key event:
        self.inject((VK_LCONTROL, True), (VK_C, True))
        self.events.clear()
        self.keyboard.Win32Keyboard.clear_keys_pressed([VK_C])
        self.assertEqual(self.events, [(VK_C, False), (VK_LCONTROL, False)])
        self.assertFalse(self.keyboard.injected_modifiers.held)

    def test_clear_keys_pressed_once(self):
        self.inject((VK_LCONTROL, True), (VK_C, True))
        self.events.clear()
        self.keyboard.Win32Keyboard.clear_keys_pressed([VK_LCONTROL, VK_C])
        self.assertEqual(self.events, [(VK_LCONTROL, False), (VK_C, False)])


@unittest.skipUnless(WIN32, "the win32 keyboard is only available on MS Windows")
class KeycodeTest(unittest.TestCase):

    def get_keycode(self, keyname: str, keystr: str = "\0") -> int:
        from xpra.platform.win32.keyboard_config import KeyboardConfig
        # GTK clients send a NUL string for the keys that have no character:
        return KeyboardConfig().get_keycode(0, keyname, True, [], 0, keystr, 0)[0]

    def test_keypad_without_numlock(self):
        for keyname, vk in {
            "KP_Home": 0x24,
            "KP_Up": 0x26,
            "KP_Page_Up": 0x21,
            "KP_Prior": 0x21,
            "KP_Left": 0x25,
            "KP_Begin": 0x0C,
            "KP_Right": 0x27,
            "KP_End": 0x23,
            "KP_Down": 0x28,
            "KP_Page_Down": 0x22,
            "KP_Next": 0x22,
            "KP_Insert": 0x2D,
            "KP_Delete": 0x2E,
            "KP_Enter": 0x0D,
        }.items():
            self.assertEqual(self.get_keycode(keyname), vk, keyname)

    def test_keypad_with_numlock(self):
        self.assertEqual(self.get_keycode("KP_9", "9"), 0x69)

    def test_page_keys(self):
        self.assertEqual(self.get_keycode("Page_Up"), 0x21)
        self.assertEqual(self.get_keycode("Page_Down"), 0x22)

    def test_control_character(self):
        # `Control+Shift+2` would type `2`:
        self.assertEqual(self.get_keycode("UnknownKey"), -1)

    def test_vk_x11_names(self):
        # the names sent by the native win32 client:
        from xpra.platform.win32.keyboard import VK_X11_MAP
        self.assertEqual(VK_X11_MAP["PRIOR"], "Page_Up")
        self.assertEqual(VK_X11_MAP["NEXT"], "Page_Down")
        self.assertEqual(VK_X11_MAP["HOME"], "Home")
        self.assertEqual(VK_X11_MAP["RETURN"], "Return")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
