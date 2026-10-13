#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import unittest
from unittest.mock import patch

OSX = sys.platform == "darwin"


class FakeClient:

    def after_handshake(self, _callback, *_args) -> None:
        pass


class FakeMenuItem:

    def __init__(self, label=""):
        self.label = label

    def set_submenu(self, _submenu) -> None:
        pass

    def show_all(self) -> None:
        pass

    def hide(self) -> None:
        pass


class FakeMenuBar:

    def __init__(self):
        self.children = []

    def add(self, item) -> None:
        self.children.append(item)

    def remove(self, item) -> None:
        self.children.remove(item)

    def get_children(self):
        return list(self.children)

    def show_all(self) -> None:
        pass


@unittest.skipUnless(OSX, "the macOS menu is only available on macOS")
class DarwinMenuTest(unittest.TestCase):

    def setUp(self) -> None:
        icon_size_patcher = patch("xpra.client.gui.menu_helper.get_icon_size", return_value=16)
        icon_size_patcher.start()
        self.addCleanup(icon_size_patcher.stop)

    @staticmethod
    def make_helper():
        from xpra.platform.darwin import menu
        helper = menu.OSXMenuHelper(FakeClient())
        helper.menu_bar = FakeMenuBar()
        helper.menuitem = lambda label, *_args, **_kwargs: FakeMenuItem(label)
        helper.get_extra_menus = lambda: [("Info", object()), ("Features", object()), ("Clipboard", object())]
        return helper

    def test_initialization_without_client(self):
        from xpra.platform.darwin import menu
        helper = menu.OSXMenuHelper()
        helper.add_full_menu()
        helper.cleanup()
        self.assertIsNone(helper.client)
        self.assertFalse(helper.full)

    def test_client_change_repopulates_menus(self):
        helper = self.make_helper()
        helper.add_full_menu()
        old_items = helper.menu_bar.get_children()
        helper.set_client(helper.client)
        self.assertTrue(helper.full)
        self.assertEqual(helper.menu_bar.get_children(), old_items)
        client = FakeClient()
        helper.set_client(client)
        self.assertIs(helper.client, client)
        self.assertFalse(helper.full)
        self.assertEqual(helper.menu_bar.get_children(), [])
        helper.add_full_menu()
        items = helper.menu_bar.get_children()
        self.assertEqual([item.label for item in items], ["Clipboard", "Features", "Info"])
        self.assertTrue(all(item not in old_items for item in items))

    def test_reconnect_repopulates_menus(self):
        helper = self.make_helper()
        helper.add_full_menu()
        self.assertTrue(helper.full)
        helper.cleanup()
        self.assertFalse(helper.full)
        self.assertEqual(helper.menu_bar.get_children(), [])
        helper.set_client(FakeClient())
        helper.add_full_menu()
        labels = [item.label for item in helper.menu_bar.get_children()]
        self.assertEqual(labels, ["Clipboard", "Features", "Info"])


def main():
    unittest.main()


if __name__ == "__main__":
    main()
