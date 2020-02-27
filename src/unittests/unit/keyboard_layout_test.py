#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.keyboard.layouts import parse_xkbmap_query

class KeyboardLayoutTest(unittest.TestCase):

    def test_parse_xkbmap_query(self):
        d = parse_xkbmap_query("""rules:      evdev
model:      pc105
layout:     gb,us,gb
variant:    ,,
""")
        assert d.get("rules")=="evdev"
        assert d.get("layout")=="gb,us,gb"
        assert not d.get("variant")


def main():
    unittest.main()

if __name__ == '__main__':
    main()
