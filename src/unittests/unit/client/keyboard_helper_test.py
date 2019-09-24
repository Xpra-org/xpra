#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct
from xpra.client.keyboard_helper import KeyboardHelper
from unit.process_test_util import DisplayContext


class KeyboardHelperTest(unittest.TestCase):

	def test_modifier(self):
		kh = KeyboardHelper(None)
		def checkmask(mask, *modifiers):
			#print("checkmask(%s, %s)", mask, modifiers)
			mods = kh.mask_to_names(mask)
			assert set(mods)==set(modifiers), "expected %s got %s" % (modifiers, mods)
		from gi.repository import Gdk
		checkmask(Gdk.ModifierType.SHIFT_MASK, "shift")
		checkmask(Gdk.ModifierType.LOCK_MASK, "lock")
		if getattr(kh.keyboard, "swap_keys", False):
			checkmask(Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.META_MASK, "shift", "control")
			#turn swap off and run again:
			kh.keyboard.swap_keys = False
		checkmask(Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.CONTROL_MASK, "shift", "control")
		kh.cleanup()

	def test_keymap_properties(self):
		kh = KeyboardHelper(None)
		p = kh.get_keymap_properties()
		assert p and len(p)>10
		kh.cleanup()

	def test_parse_shortcuts(self):
		kh = KeyboardHelper(None)
		shortcuts = [
			'Control+Menu:toggle_keyboard_grab',
			'Shift+Menu:toggle_pointer_grab',
			'Shift+F11:toggle_fullscreen',
			'#+F1:show_menu',
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
		parsed = kh.parse_shortcuts(shortcuts)
		assert len(parsed)>10
		def noop():
			pass
		window = AdHocStruct()
		window.quit = noop
		assert kh.key_handled_as_shortcut(window, "F4", ("mod1", "shift"), True)
		assert not kh.key_handled_as_shortcut(window, "F1", (), True)
		kh.cleanup()


def main():
	with DisplayContext():
		unittest.main()


if __name__ == '__main__':
	main()
