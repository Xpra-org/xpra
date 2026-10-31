#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.client.subsystem import command
from xpra.client.subsystem.command import validated_menu, MAX_MENU_NAME


def make_menu(categories: int, entries: int) -> dict:
    return {
        f"category{c:03}": {
            "IconType": "png",
            "Entries": {f"app{e:03}": {"command": f"app{e}"} for e in range(entries)},
        } for c in range(categories)
    }


class MenuTest(unittest.TestCase):

    def test_small_menu(self):
        menu = make_menu(2, 3)
        self.assertEqual(validated_menu(menu), (menu, False))

    def test_invalid(self):
        self.assertEqual(validated_menu(None), ({}, False))
        self.assertEqual(validated_menu({"category": "not a dict"}), ({}, False))
        menu, trimmed = validated_menu({"category": {"Entries": {"app": "not a dict", "other": {}}}})
        self.assertEqual(menu, {"category": {"Entries": {"other": {}}}})
        self.assertFalse(trimmed)

    def test_names(self):
        menu, _ = validated_menu({
            "Game‮s": {"Entries": {b"Term\x1b[2Jinal\n": {"command": "xterm"}, "x" * 1000: {}}},
        })
        self.assertEqual(list(menu), ["Games"])
        names = list(menu["Games"]["Entries"])
        self.assertIn("Term[2Jinal", names)
        self.assertEqual(max(len(name) for name in names), MAX_MENU_NAME)

    def test_labels(self):
        menu, _ = validated_menu({"Accessories": {"Entries": {
            "org.gnome.Nautilus": {"Name": "Files", "command": "nautilus"},
            "nemo": {"Name": "Files", "command": "nemo"},
            "org.gnome.Calculator": {"Name": b"Calculator", "command": "gnome-calculator"},
            "xterm": {"command": "xterm"},
        }}})
        entries = menu["Accessories"]["Entries"]
        self.assertEqual(list(entries), ["Calculator", "Files (nemo)", "Files (org.gnome.Nautilus)", "xterm"])
        self.assertEqual(entries["Files (nemo)"]["command"], "nemo")

    def test_limits(self):
        menu, trimmed = validated_menu(make_menu(command.MAX_MENU_CATEGORIES * 2, command.MAX_MENU_ENTRIES * 2))
        self.assertTrue(trimmed)
        self.assertEqual(list(menu), [f"category{c:03}" for c in range(command.MAX_MENU_CATEGORIES)])
        for props in menu.values():
            self.assertEqual(props["IconType"], "png")
            self.assertEqual(list(props["Entries"]), [f"app{e:03}" for e in range(command.MAX_MENU_ENTRIES)])

    def test_override(self):
        with patch.object(command, "MAX_MENU_CATEGORIES", 2), patch.object(command, "MAX_MENU_ENTRIES", 3):
            menu, trimmed = validated_menu(make_menu(5, 5))
        self.assertTrue(trimmed)
        self.assertEqual(len(menu), 2)
        self.assertEqual(len(menu["category000"]["Entries"]), 3)

    def test_notify_once(self):
        client = command.CommandClient()
        callbacks = {}
        client.client = type("FakeClient", (), {
            "on_server_setting_changed": lambda _self, setting, cb: callbacks.__setitem__(setting, cb),
        })()
        client.parse_server_capabilities(command.typedict({"start-new-commands": True}))
        with patch.object(command, "may_notify_client") as notify, patch.object(command, "first_time", side_effect=[True, False]):
            callbacks["menu"]("menu", make_menu(command.MAX_MENU_CATEGORIES + 1, 1))
            callbacks["menu"]("menu", make_menu(command.MAX_MENU_CATEGORIES + 1, 1))
        notify.assert_called_once()
        self.assertEqual(notify.call_args.args[1], command.NotificationID.MENU)
        self.assertEqual(len(client.server_menu), command.MAX_MENU_CATEGORIES)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
