#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.keyboard.common import KeyEvent


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


def main():
    unittest.main()


if __name__ == '__main__':
    main()
