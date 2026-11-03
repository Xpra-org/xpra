#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""The `show_menu` key shortcut works without a tray to create the menu first."""

import unittest
from unittest.mock import Mock

from xpra.client.gui.ui_client_base import UIXpraClient


class ShowMenuTest(unittest.TestCase):

    def make_client(self, helper_class) -> UIXpraClient:
        client = UIXpraClient.__new__(UIXpraClient)
        client.menu_helper = None
        client.get_menu_helper_class = lambda: helper_class
        return client

    def test_no_tray(self) -> None:
        helper = Mock()
        client = self.make_client(lambda _client: helper)
        client.show_menu()
        helper.activate.assert_called_once_with()
        # the same menu is used the next time:
        client.show_menu()
        self.assertEqual(helper.activate.call_count, 2)
        self.assertIs(client.menu_helper, helper)

    def test_no_menu(self) -> None:
        client = self.make_client(None)
        client.show_menu()
        self.assertIsNone(client.menu_helper)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
