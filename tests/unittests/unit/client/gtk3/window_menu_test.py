#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Test the window menu items which act on the window (no display needed: menu items are faked)."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.client.gui.fake_client import FakeClient
from xpra.client.gtk3.window.menu import WindowMenuHelper


class MenuHelper:
    make_bordermenuitem = WindowMenuHelper.make_bordermenuitem
    make_refreshmenuitem = WindowMenuHelper.make_refreshmenuitem
    make_grabmenuitem = WindowMenuHelper.make_grabmenuitem

    def __init__(self):
        self.get_subsystem = FakeClient().get_subsystem
        self.window = Mock(wid=5, border=SimpleNamespace(shown=False))
        self.ticked = []

    @staticmethod
    def menuitem(title, icon, cb):
        return SimpleNamespace(title=title, activate=cb)

    def _set_ticked(self, item, ticked: bool) -> None:
        self.ticked.append((item.title, ticked))


class WindowMenuTest(unittest.TestCase):

    def test_border(self) -> None:
        helper = MenuHelper()
        helper.make_grabmenuitem()
        item = helper.make_bordermenuitem()
        item.activate()
        self.assertTrue(helper.window.border.shown)
        # the border item is the one ticked, not the grab item:
        self.assertEqual(helper.ticked, [("Show Border", True)])
        helper.window.refresh_window.assert_called_once_with()

    def test_refresh(self) -> None:
        helper = MenuHelper()
        helper.make_refreshmenuitem().activate()
        helper.window.refresh_window.assert_called_once_with()
        helper.window.reset_icon.assert_called_once_with()

    def test_grab(self) -> None:
        helper = MenuHelper()
        window_subsystem = helper.get_subsystem("window")
        item = helper.make_grabmenuitem()
        item.activate()
        self.assertTrue(window_subsystem.is_grabbed(5))
        item.activate()
        self.assertFalse(window_subsystem.is_grabbed(5))
        self.assertEqual(helper.ticked, [("Grabbed", True), ("Grabbed", False)])

    def test_no_client(self) -> None:
        # the window menu is given the window's subsystem lookup, never the client:
        get_subsystem = Mock()
        # (the icon size would otherwise come from the X11 settings)
        with patch("xpra.client.gui.menu_helper.get_icon_size", return_value=24):
            helper = WindowMenuHelper(get_subsystem, Mock())
        self.assertIsNone(helper.client)
        self.assertIs(helper.get_subsystem, get_subsystem)
        # windows only exist after the handshake, so nothing waits for it:
        self.assertEqual(helper.handshake_menuitem, helper.menuitem)
        helper.after_handshake(self.fail)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
