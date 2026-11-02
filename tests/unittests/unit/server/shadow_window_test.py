#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.objects import AdHocStruct
from xpra.net.common import Packet


class FakeKeyboard:
    """ records the calls to `clear_keys_pressed` """

    def __init__(self, keys_pressed: dict[int, str]):
        self.keys_pressed = keys_pressed
        self.cleared = 0

    def clear_keys_pressed(self) -> None:
        self.cleared += 1
        self.keys_pressed = {}


class ShadowWindowFocusTest(unittest.TestCase):

    def make_window_server(self, ui_driver="client", readonly=False):
        from xpra.server.shadow.window import ShadowWindowServer
        window = ShadowWindowServer.__new__(ShadowWindowServer)
        keyboard = FakeKeyboard({164: "Alt_L"})
        source = AdHocStruct()
        source.uuid = "client"
        source.user_event = lambda *_args: None
        server = AdHocStruct()
        server.subsystems = {"keyboard": keyboard}
        server.ui_driver = ui_driver
        server.readonly = readonly
        server.get_server_source = lambda _proto: source
        window.server = server
        window._id_to_window = {}
        return window, keyboard

    def focus(self, window, wid: int) -> None:
        window._process_focus(object(), Packet("window-focus", wid, ["mod2"]))

    def test_focus_lost_releases_the_keys(self):
        # ie: `Alt+Tab` on the client sends the press of `Alt` but not its release
        for ui_driver in ("client", None):
            with self.subTest(ui_driver=ui_driver):
                window, keyboard = self.make_window_server(ui_driver)
                self.focus(window, 0)
                self.assertEqual(keyboard.cleared, 1)
                self.assertEqual(keyboard.keys_pressed, {})

    def test_focus_gained_keeps_the_keys(self):
        window, keyboard = self.make_window_server()
        self.focus(window, 1)
        self.assertEqual(keyboard.cleared, 0)
        self.assertEqual(keyboard.keys_pressed, {164: "Alt_L"})

    def test_other_client_keeps_the_keys(self):
        # the keys pressed belong to the client driving the session, not to this one:
        window, keyboard = self.make_window_server("another-client")
        self.focus(window, 0)
        self.assertEqual(keyboard.cleared, 0)

    def test_readonly_client_keeps_the_keys(self):
        window, keyboard = self.make_window_server(readonly=True)
        self.focus(window, 0)
        self.assertEqual(keyboard.cleared, 0)

    def test_nothing_pressed(self):
        window, keyboard = self.make_window_server()
        keyboard.keys_pressed = {}
        self.focus(window, 0)
        self.assertEqual(keyboard.cleared, 0)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
