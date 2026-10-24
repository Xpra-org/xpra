#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch


class TestX11Info(unittest.TestCase):

    def setUp(self):
        for p in (patch("xpra.x11.error.Xenter"), patch("xpra.x11.error.Xexit", return_value=0)):
            self.enterContext(p)

    def test_destroyed_parent_stops_lookup(self):
        from xpra.x11 import info
        from xpra.x11.error import XError
        window = Mock()
        # A second result bounds the regression on the old, retrying code.
        window.getParent.side_effect = [XError("window destroyed"), 0]
        with patch.object(info, "X11WindowBindings", return_value=window), \
                patch.object(info, "get_wintitle", return_value=""), \
                patch.dict("sys.modules", {"xpra.x11.bindings.res": None}), \
                patch("xpra.x11.error.Xenter"), patch("xpra.x11.error.Xexit", return_value=0):
            self.assertEqual(info.get_wininfo(123), "xid=7b")
        window.getParent.assert_called_once_with(123)

    def test_window_title_encodings_and_fallbacks(self):
        from xpra.x11 import info
        from xpra.x11.error import XError
        for legacy, modern, expected in (
            (b"caf\xe9", b"unused", "café"),
            (None, "λ".encode(), "λ"),
            (b"", b"", ""),
            (None, b"\xff", ""),
            (XError("legacy unavailable"), b"modern", "modern"),
            (XError("window gone"), XError("window gone"), ""),
        ):
            with self.subTest(expected=expected):
                window = Mock()
                window.XGetWindowProperty.side_effect = [legacy, modern]
                with patch.object(info, "X11WindowBindings", return_value=window):
                    self.assertEqual(info.get_wintitle(123), expected)
                calls = window.XGetWindowProperty.call_args_list
                self.assertEqual(calls[0].args, (123, "WM_NAME", "STRING"))
                if not legacy or isinstance(legacy, Exception):
                    self.assertEqual(calls[1].args, (123, "_NET_WM_NAME", "UTF8_STRING"))
                else:
                    self.assertEqual(len(calls), 1)

    def test_window_title_and_pid(self):
        from xpra.x11 import info
        resource = Mock()
        resource.get_pid.return_value = 456
        module = SimpleNamespace(ResBindings=Mock(return_value=resource))
        with patch.dict("sys.modules", {"xpra.x11.bindings.res": module}), \
                patch.object(info, "get_wintitle", return_value="Terminal"):
            self.assertEqual(info.get_wininfo(123), "'Terminal', xid=7b, pid=456")
        resource.get_pid.assert_called_once_with(123)

    def test_optional_pid_lookup(self):
        from xpra.x11 import info
        from xpra.x11.error import XError
        for supported, pid in ((False, 456), (True, 0), (True, XError("window gone"))):
            with self.subTest(supported=supported, pid=pid):
                resource = Mock()
                resource.check_xres.return_value = supported
                if isinstance(pid, Exception):
                    resource.get_pid.side_effect = pid
                else:
                    resource.get_pid.return_value = pid
                module = SimpleNamespace(ResBindings=Mock(return_value=resource))
                with patch.dict("sys.modules", {"xpra.x11.bindings.res": module}), \
                        patch.object(info, "get_wintitle", return_value="Terminal"):
                    self.assertEqual(info.get_wininfo(123), "'Terminal', xid=7b")
                self.assertEqual(resource.get_pid.call_count, int(supported))

    def test_parent_title_and_unnamed_window(self):
        from xpra.x11 import info
        window = Mock()
        titles = {123: "", 456: "Parent"}
        with patch.dict("sys.modules", {"xpra.x11.bindings.res": None}), \
                patch.object(info, "X11WindowBindings", return_value=window), \
                patch.object(info, "get_wintitle", side_effect=titles.get):
            window.getParent.return_value = 456
            self.assertEqual(info.get_wininfo(123), "xid=7b, child of 'Parent'")
            window.getParent.assert_called_once_with(123)
            window.getParent.reset_mock()
            window.getParent.return_value = 0
            self.assertEqual(info.get_wininfo(123), "xid=7b")
            window.getParent.assert_called_once_with(123)

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
