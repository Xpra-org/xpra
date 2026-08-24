#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Yan Shoshitaishvili <yans@pwn.college>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.keyboard.common import KeyEvent
from xpra.keyboard.mask import MODIFIER_MAP, DEFAULT_MODIFIER_MEANINGS

try:
    from xpra.client.terminal import keyboard as terminal_keyboard
    from xpra.client.terminal.input import parse_mouse_params, MOD_CAPS_LOCK, MOD_NUM_LOCK, MOD_SUPER
    from xpra.client.terminal.keys import modifier_names
except ImportError:
    terminal_keyboard = None

# every method `KeyboardHelper` calls on the keyboard object:
KEYBOARD_METHODS = (
    "mask_to_names", "set_modifier_mappings", "get_keymap_modifiers", "get_keymap_spec",
    "get_x11_keymap", "get_layout_spec", "get_keyboard_repeat", "update_modifier_map",
    "process_key_event", "cleanup", "has_bell",
)


@unittest.skipIf(terminal_keyboard is None, "the terminal client component is not available")
class TerminalKeyboardTest(unittest.TestCase):

    def test_contract(self):
        keyboard = terminal_keyboard.TerminalKeyboard()
        for method in KEYBOARD_METHODS:
            self.assertTrue(callable(getattr(keyboard, method, None)), f"no {method!r} method")
        self.assertEqual(repr(keyboard), "TerminalKeyboard")

    def test_keymap_modifiers(self):
        keyboard = terminal_keyboard.TerminalKeyboard()
        mod_meanings, mod_managed, mod_pointermissing = keyboard.get_keymap_modifiers()
        self.assertEqual(mod_managed, [])
        # SGR mouse reports only have room for `shift`, `mod1` and `control`,
        # everything else is missing from our pointer events:
        self.assertEqual(mod_pointermissing, ["lock", "mod2", "mod3", "mod4", "mod5"])
        # the caller gets a copy it can modify:
        mod_pointermissing.append("shift")
        self.assertEqual(keyboard.get_keymap_modifiers()[2], ["lock", "mod2", "mod3", "mod4", "mod5"])
        self.assertTrue(mod_meanings)
        for keyname, modifier in mod_meanings.items():
            self.assertEqual(DEFAULT_MODIFIER_MEANINGS.get(keyname), modifier)
            self.assertIn(modifier, MODIFIER_MAP)
        for keyname in ("Shift_L", "Control_R", "Alt_L", "Caps_Lock", "Num_Lock", "Super_L"):
            self.assertIn(keyname, mod_meanings, f"{keyname!r} is missing")
        # `Mode_switch` is not a key the terminal can report:
        self.assertNotIn("Mode_switch", mod_meanings)
        # the caller gets a copy it can modify:
        mod_meanings["Shift_L"] = "mod5"
        self.assertEqual(keyboard.get_keymap_modifiers()[0]["Shift_L"], "shift")

    def test_pointermissing_matches_the_mouse_reports(self):
        # an SGR motion report (mode 1003) with every modifier bit the format has:
        # `ESC [ < 63 ; 10 ; 10 M` - button bits 32+3, modifier bits 4, 8 and 16
        events = parse_mouse_params(([32 + 3 + 4 + 8 + 16], [10], [10]), ord("M"))
        self.assertEqual(len(events), 1)
        reported = modifier_names(events[0].mods)
        self.assertEqual(sorted(reported), ["control", "mod1", "shift"])
        mod_pointermissing = terminal_keyboard.TerminalKeyboard().get_keymap_modifiers()[2]
        # what we do report must not be declared missing:
        self.assertEqual(set(reported) & set(mod_pointermissing), set())
        # and everything the server may see in a key event but never in a mouse event must be:
        declared = set(terminal_keyboard.MOD_MEANINGS.values())
        self.assertEqual(declared - set(reported), set(mod_pointermissing))
        # a key event does carry the lock modifiers and `Super`:
        key_mods = modifier_names(MOD_CAPS_LOCK | MOD_NUM_LOCK | MOD_SUPER)
        self.assertEqual(sorted(key_mods), ["lock", "mod2", "mod3"])
        for modifier in key_mods:
            self.assertIn(modifier, mod_pointermissing, f"{modifier!r} is reported by key events only")

    def test_layout_spec(self):
        keyboard = terminal_keyboard.TerminalKeyboard()
        model, layout, layouts, variant, variants, options = keyboard.get_layout_spec()
        self.assertEqual(model, "pc105")
        self.assertEqual(layout, "us")
        self.assertEqual(list(layouts), ["us"])
        self.assertEqual(variant, "")
        self.assertEqual(list(variants), [])
        self.assertEqual(options, "")

    def test_no_local_keymap(self):
        keyboard = terminal_keyboard.TerminalKeyboard()
        # no key repeat: each repeat is delivered as a new key press
        # (`keyboard_sync` is turned off by the client's `init`):
        self.assertIsNone(keyboard.get_keyboard_repeat())
        self.assertEqual(keyboard.get_keymap_spec(), {})
        self.assertEqual(keyboard.get_x11_keymap(), {})
        self.assertEqual(keyboard.mask_to_names(MODIFIER_MAP["control"] | MODIFIER_MAP["shift"]),
                         ["shift", "control"])

    def test_process_key_event(self):
        keyboard = terminal_keyboard.TerminalKeyboard()
        key_event = KeyEvent()
        key_event.keyname = "a"
        sent = []
        keyboard.process_key_event(lambda wid, event: sent.append((wid, event)), 1, key_event)
        # the default is to send the event as-is:
        self.assertEqual(sent, [(1, key_event)])


@unittest.skipIf(terminal_keyboard is None, "the terminal client component is not available")
class TerminalKeyboardHelperTest(unittest.TestCase):

    def make_helper(self, *args):
        packets = []
        helper = terminal_keyboard.TerminalKeyboardHelper(lambda *packet: packets.append(packet), *args)
        self.addCleanup(helper.cleanup)
        return helper, packets

    def test_keyboard_class(self):
        helper = self.make_helper()[0]
        # the `make_keyboard` factory must be used instead of the platform keyboard:
        self.assertIsInstance(helper.keyboard, terminal_keyboard.TerminalKeyboard)
        self.assertIsInstance(helper.make_keyboard(), terminal_keyboard.TerminalKeyboard)
        self.assertEqual(repr(helper), "TerminalKeyboardHelper")
        # no key repeat value means no keyboard synchronization:
        self.assertEqual((helper.key_repeat_delay, helper.key_repeat_interval), (-1, -1))

    def test_keymap_properties(self):
        helper = self.make_helper()[0]
        props = helper.get_keymap_properties()
        self.assertEqual(props.get("layout"), "us")
        self.assertEqual(list(props.get("layouts")), ["us"])
        self.assertEqual(props.get("mod_meanings"), terminal_keyboard.MOD_MEANINGS)
        # the server needs this to leave the lock modifiers alone on pointer events:
        self.assertEqual(props.get("mod_pointermissing"), list(terminal_keyboard.MOD_POINTERMISSING))
        # empty values are not sent at all, and we have no modifier for the server to manage:
        self.assertNotIn("mod_managed", props)
        # we have no keycodes to send: the server maps the key names we send instead
        self.assertNotIn("keycodes", props)
        self.assertNotIn("x11_keycodes", props)
        self.assertNotIn("query_struct", props)
        # what the `keyboard` subsystem skips when the keyboard data is delayed:
        self.assertEqual(helper.get_keymap_properties(("layout", )).get("layout"), None)

    def test_keyboard_sync_off_is_sent_to_the_server(self):
        # the server defaults to sync=True, so a `False` must actually be sent
        # in the keymap properties - it must not be dropped as a falsy value:
        helper = self.make_helper(False)[0]
        self.assertIs(helper.sync, False)
        self.assertIs(helper.get_keymap_properties().get("sync"), False)

    def test_send_key_action(self):
        helper, packets = self.make_helper()
        key_event = KeyEvent()
        key_event.keyname = "Return"
        key_event.pressed = True
        key_event.modifiers = ["control"]
        helper.process_key_event(1, key_event)
        self.assertEqual(len(packets), 1)
        packet = packets[0]
        self.assertIn(packet[0], ("key-action", "keyboard-event"))
        self.assertEqual(packet[1], 1)
        self.assertEqual(packet[2], "Return")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
