#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.server.source.display import DisplayConnection, MAX_DESKTOP_NAMES, MAX_DESKTOP_NAME


class DisplayConnectionTest(unittest.TestCase):

    def test_desktop_names_are_cleaned(self):
        dc = DisplayConnection()
        dc.init_state()
        # a NUL would split the `_NET_DESKTOP_NAMES` list:
        dc.set_desktops(3, ("one\0two", "line1\nline2‮", "x" * 1000))
        self.assertEqual(dc.desktops, 3)
        self.assertEqual(dc.desktop_names[:2], ("onetwo", "line1 line2"))
        self.assertEqual(len(dc.desktop_names[2]), MAX_DESKTOP_NAME)

    def test_desktop_names_are_limited(self):
        dc = DisplayConnection()
        dc.init_state()
        dc.set_desktops(1000, tuple(str(i) for i in range(1000)))
        self.assertEqual(len(dc.desktop_names), MAX_DESKTOP_NAMES)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
