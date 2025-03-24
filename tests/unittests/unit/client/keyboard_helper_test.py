#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.common import noop
from xpra.util.objects import AdHocStruct
from xpra.client.gui.keyboard_helper import KeyboardHelper
from unit.process_test_util import DisplayContext


class KeyboardHelperTest(unittest.TestCase):

    def test_modifier(self):
        kh = KeyboardHelper(noop)

        def checkmask(mask, *modifiers):
            #print("checkmask(%s, %s)", mask, modifiers)
            mods = kh.mask_to_names(mask)
            assert set(mods) == set(modifiers), "expected %s got %s" % (modifiers, mods)

        from gi.repository import Gdk  # @UnresolvedImport
        checkmask(Gdk.ModifierType.SHIFT_MASK, "shift")
        checkmask(Gdk.ModifierType.LOCK_MASK, "lock")
        if getattr(kh.keyboard, "swap_keys", False):
            checkmask(Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.META_MASK, "shift", "control")
            #turn swap off and run again:
            kh.keyboard.swap_keys = False
        checkmask(Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.CONTROL_MASK, "shift", "control")
        kh.cleanup()

    def test_keymap_properties(self):
        kh = KeyboardHelper(noop)
        kh.query_xkbmap()
        p = kh.get_keymap_properties()
        assert p, "no keymap properties returned"
        assert len(p) >= 8, "not enough keymap properties (%i): %s" % (len(p), p)
        kh.cleanup()

    def test_parse_shortcuts(self):
        shortcuts = [
            'Control+Menu:toggle_keyboard_grab',
            'Shift+Menu:toggle_pointer_grab',
            'Shift+F11:toggle_fullscreen',
            '#+F1:show_menu',
            'Control+F1:show_window_menu',
            '#+F2:show_start_new_command',
            '#+F3:show_bug_report',
            '#+F4:quit',
            '#+F5:increase_quality',
            '#+F6:decrease_quality',
            '#+F7:increase_speed',
            '#+F8:decrease_speed',
            '#+F10:magic_key',
            '#+F11:show_session_info',
            '#+F12:toggle_debug',
            '#+plus:scaleup',
            '#+minus:scaledown',
            '#+underscore:scaledown',
            '#+KP_Add:scaleup',
            '#+KP_Subtract:scaledown',
            '#+KP_Multiply:scalereset',
            '#+bar:scalereset',
            '#+question:scalingoff',
        ]
        kh = KeyboardHelper(noop, key_shortcuts=shortcuts)
        parsed = kh.parse_shortcuts()
        assert kh.shortcut_modifiers, "no shortcut modifiers: %s" % (kh.shortcut_modifiers,)
        assert len(parsed) > 10, "not enough shortcuts parsed: %s" % (parsed,)
        window = AdHocStruct()
        window.quit = noop
        modifier_names = kh.get_modifier_names()
        modifiers_used = [modifier_names.get(x, x) for x in kh.shortcut_modifiers]
        assert kh.key_handled_as_shortcut(window, "F4", modifiers_used, True)
        assert not kh.key_handled_as_shortcut(window, "F1", [], True)
        kh.cleanup()


def main():
    with DisplayContext():
        unittest.main()


if __name__ == '__main__':
    main()
