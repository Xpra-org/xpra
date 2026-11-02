#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock

from xpra.client.gui.shortcuts import ShortcutTarget, CLIENT_ACTIONS


class Window:
    def __init__(self):
        self.calls = []

    def show_window_info(self, *args):
        self.calls.append(("show_window_info", args))

    def show_menu(self, *args):
        self.calls.append(("show_menu", args))


class ShortcutTargetTest(unittest.TestCase):

    def test_window_first(self) -> None:
        window = Window()
        client = Mock()
        target = ShortcutTarget(client, window)
        target.show_window_info()
        target.show_menu(1)
        self.assertEqual(window.calls, [("show_window_info", ()), ("show_menu", (1, ))])
        client.show_menu.assert_not_called()

    def test_client_actions(self) -> None:
        client = Mock()
        target = ShortcutTarget(client, object())
        for action in sorted(CLIENT_ACTIONS):
            getattr(target, action)("arg")
            getattr(client, action).assert_called_once_with("arg")

    def test_other_client_methods_are_refused(self) -> None:
        client = Mock()
        target = ShortcutTarget(client, object())
        for action in ("cleanup", "send", "__class__x", "missing"):
            with self.assertRaises(AttributeError):
                getattr(target, action)
        client.cleanup.assert_not_called()

    def test_own_actions(self) -> None:
        client = Mock()
        target = ShortcutTarget(client, object())
        target.void("ignored")
        target.download_server_log("not-a-callback")
        client.download_server_log.assert_called_once_with()


def main():
    unittest.main()


if __name__ == '__main__':
    main()
