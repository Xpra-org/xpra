#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest


class TestX11Info(unittest.TestCase):

    def test_no_window_is_not_looked_up(self):
        # `XNone` must not reach the server: no display is opened here,
        # so any window or pid lookup would fail outright
        from xpra.x11.info import get_wininfo
        self.assertEqual(get_wininfo(0), "None")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
