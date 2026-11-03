#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
The `show_menu` key shortcut and the windows' header bar share the tray's xpra menu,
unless that one cannot be popped up (the macOS menu bar).
"""

import unittest
from unittest.mock import Mock, patch

from xpra.client.gui.ui_client_base import UIXpraClient


def make_helper(can_popup=True) -> Mock:
    helper = Mock()
    helper.can_popup = can_popup
    return helper


def init_client(client, helper: Mock | None):
    client.menu_helper = None
    client.get_menu_helper_class = lambda: (lambda _client: helper) if helper else None
    return client


class ShowMenuTest(unittest.TestCase):

    @staticmethod
    def make_client(helper: Mock | None) -> UIXpraClient:
        return init_client(UIXpraClient.__new__(UIXpraClient), helper)

    def test_no_tray(self) -> None:
        helper = make_helper()
        client = self.make_client(helper)
        client.show_menu()
        # nothing has built the menu yet:
        helper.build.assert_called_once_with()
        helper.activate.assert_called_once_with()
        # the same menu is used the next time:
        client.show_menu()
        self.assertEqual(helper.activate.call_count, 2)
        self.assertIs(client.menu_helper, helper)
        self.assertIs(client.get_popup_menu_helper(), helper)

    def test_no_menu(self) -> None:
        client = self.make_client(None)
        client.show_menu()
        self.assertIsNone(client.menu_helper)
        self.assertIsNone(client.get_popup_menu_helper())

    def test_menu_bar(self) -> None:
        helper = make_helper(can_popup=False)
        client = self.make_client(helper)
        self.assertIsNone(client.get_popup_menu_helper())
        client.show_menu()
        helper.activate.assert_not_called()


class GTKPopupMenuTest(unittest.TestCase):

    @staticmethod
    def make_client(helper: Mock | None):
        try:
            from xpra.client.gtk3.client_base import GTKXpraClient
        except ImportError as e:
            raise unittest.SkipTest(f"no gtk3 client: {e}")
        client = init_client(GTKXpraClient.__new__(GTKXpraClient), helper)
        client.popup_menu_helper = None
        # (`GTKXpraClient.get_menu_helper` uses the platform's menu class)
        client.get_menu_helper = lambda: UIXpraClient.get_menu_helper(client)
        return client

    def test_shared(self) -> None:
        helper = make_helper()
        client = self.make_client(helper)
        with patch("xpra.client.gtk3.tray_menu.GTKTrayMenu") as menu_class:
            self.assertIs(client.get_popup_menu_helper(), helper)
            self.assertIs(client.get_window_menu_helper(), helper)
            menu_class.assert_not_called()
        self.assertIsNone(client.popup_menu_helper)

    def test_menu_bar(self) -> None:
        client = self.make_client(make_helper(can_popup=False))
        with patch("xpra.client.gtk3.tray_menu.GTKTrayMenu") as menu_class:
            popup = client.get_popup_menu_helper()
            self.assertIs(popup, menu_class.return_value)
            # created only once:
            self.assertIs(client.get_popup_menu_helper(), popup)
            menu_class.assert_called_once_with(client)
            client.show_menu()
            popup.build.assert_called_once_with()
            popup.activate.assert_called_once_with()


def main():
    unittest.main()


if __name__ == '__main__':
    main()
