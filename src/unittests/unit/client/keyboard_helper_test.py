#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.client.keyboard_helper import KeyboardHelper


class KeyboardHelperTest(unittest.TestCase):

	def test_modifier(self):
		kh = KeyboardHelper(None)
		from xpra.gtk_common.gtk_util import SHIFT_MASK, LOCK_MASK, META_MASK, CONTROL_MASK, SUPER_MASK, HYPER_MASK
		def checkmask(mask, *modifiers):
			#print("checkmask(%s, %s)", mask, modifiers)
			mods = kh.mask_to_names(mask)
			assert set(mods)==set(modifiers), "expected %s got %s" % (modifiers, mods)
		checkmask(SHIFT_MASK, "shift")
		checkmask(LOCK_MASK, "lock")
		checkmask(SHIFT_MASK | CONTROL_MASK, "shift", "control")

	def test_keymap_properties(self):
		kh = KeyboardHelper(None)
		p = kh.get_keymap_properties()
		assert p and len(p)>10

def main():
	unittest.main()


if __name__ == '__main__':
	main()
