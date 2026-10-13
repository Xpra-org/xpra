#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest


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


class DarwinMenuTest(unittest.TestCase):

    def test_reconnect_repopulates_menus(self):
        from xpra.platform.darwin import menu
        helper = object.__new__(menu.OSXMenuHelper)
        helper.client = FakeClient()
        helper.menu_bar = FakeMenuBar()
        helper.menus = {}
        helper.full = False
        helper.menu_shown = False
        helper.menuitem = lambda label, *_args, **_kwargs: FakeMenuItem(label)
        helper.get_extra_menus = lambda: [("Info", object()), ("Features", object()), ("Clipboard", object())]
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
