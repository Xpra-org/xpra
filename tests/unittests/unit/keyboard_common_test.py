#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.objects import typedict
from xpra.keyboard.common import KeyEvent, keymap_str, keymap_strtuple, MAX_KEYMAP_STRING, MAX_KEYMAP_LAYOUTS


class TestKeyEvent(unittest.TestCase):

    def test_defaults(self):
        e = KeyEvent()
        assert e.modifiers == []
        assert e.keyname == ""
        assert e.keyval == 0
        assert e.keycode == 0
        assert e.group == 0
        assert e.string == ""
        assert e.pressed is True

    def test_repr(self):
        e = KeyEvent()
        s = str(e)
        assert "KeyEvent" in s
        assert "keyname" in s

    def test_assign(self):
        e = KeyEvent()
        e.keyname = "Return"
        e.keycode = 36
        e.pressed = False
        assert e.keyname == "Return"
        assert e.keycode == 36
        assert not e.pressed


class TestKeymapStr(unittest.TestCase):

    def test_valid(self):
        d = typedict({"layout": "us,fr", "options": "grp:alt_shift_toggle,ctrl:nocaps"})
        self.assertEqual(keymap_str(d, "layout"), "us,fr")
        self.assertEqual(keymap_str(d, "options"), "grp:alt_shift_toggle,ctrl:nocaps")
        self.assertEqual(keymap_str(d, "variant", "intl"), "intl")

    def test_invalid(self):
        for value in ("us\nfr", "us\x1b[2J", "\u0434\u0435", "us\u202e", "x" * (MAX_KEYMAP_STRING + 1)):
            self.assertEqual(keymap_str(typedict({"layout": value}), "layout", "us"), "us", f"{value!r} was accepted")

    def test_tuple(self):
        d = typedict({"layouts": ("us", "fr\x1b[2J", "de"), "variants": ("x" * (MAX_KEYMAP_STRING + 1), "oss")})
        # invalid entries are blanked so the layouts and variants still match by position:
        self.assertEqual(keymap_strtuple(d, "layouts"), ("us", "", "de"))
        self.assertEqual(keymap_strtuple(d, "variants"), ("", "oss"))
        d = typedict({"layouts": ("us", ) * (MAX_KEYMAP_LAYOUTS * 4)})
        self.assertEqual(len(keymap_strtuple(d, "layouts")), MAX_KEYMAP_LAYOUTS)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
