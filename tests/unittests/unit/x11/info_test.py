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

    def test_wininfo_waits_to_be_formatted(self):
        # the debug log lines it is used in must not cost anything
        # when that log category is switched off
        from xpra.x11 import info
        calls = []

        def counting_get_wininfo(xid: int) -> str:
            calls.append(xid)
            return f"window {xid}"

        wininfo = info.WinInfo(123)
        saved, info.get_wininfo = info.get_wininfo, counting_get_wininfo
        try:
            self.assertEqual(calls, [])
            self.assertEqual(f"{wininfo}", "window 123")
            self.assertEqual(calls, [123])
        finally:
            info.get_wininfo = saved


def main():
    unittest.main()


if __name__ == '__main__':
    main()
