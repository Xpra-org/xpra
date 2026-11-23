#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from xpra.client.subsystem.command import CommandClient, labelled_menu
from xpra.util.objects import typedict


class MenuLabelsTest(unittest.TestCase):

    def test_keyed_by_desktop_file_id(self):
        menu = labelled_menu({"Accessories": {"IconType": "png", "Entries": {
            "org.gnome.Nautilus": {"Name": "Files", "command": "nautilus"},
            "nemo": {"Name": "Files", "command": "nemo"},
            "org.gnome.Calculator": {"Name": b"Calculator", "command": "gnome-calculator"},
            "xterm": {"command": "xterm"},
        }}})
        self.assertEqual(menu["Accessories"]["IconType"], "png")
        entries = menu["Accessories"]["Entries"]
        self.assertEqual(sorted(entries), ["Calculator", "Files (nemo)", "Files (org.gnome.Nautilus)", "xterm"])
        self.assertEqual(entries["Files (nemo)"]["command"], "nemo")

    def test_keyed_by_name(self):
        # older servers:
        menu = {"Accessories": {"Entries": {
            "Files": {"Name": "Files", "command": "nemo"},
            "Calculator": {"command": "gnome-calculator"},
        }}}
        self.assertEqual(labelled_menu(menu), menu)

    def test_invalid(self):
        self.assertEqual(labelled_menu(None), {})
        self.assertEqual(labelled_menu({"category": "not a dict"}), {"category": "not a dict"})
        self.assertEqual(labelled_menu({"category": {"Entries": {"app": "not a dict"}}}), {"category": {"Entries": {"app": "not a dict"}}})

    def test_menu_updated_before_ui_callbacks(self):
        callbacks = []
        fake_client = Mock()
        fake_client.on_server_setting_changed.side_effect = lambda setting, cb: callbacks.append((setting, cb))
        client = CommandClient(fake_client)
        client.init(SimpleNamespace(start_new_commands=True, start=[], start_child=[]))
        seen = []
        callbacks.append(("menu", lambda _setting, _value: seen.append(client.server_menu)))
        client.parse_server_capabilities(typedict({"start-new-commands": True}))
        menu = {"Accessories": {"Entries": {"org.gnome.Nautilus": {"Name": "Files", "command": "nautilus"}}}}
        for setting, callback in callbacks:
            if setting == "menu":
                callback(setting, menu)
        self.assertEqual(seen, [labelled_menu(menu)])


def main():
    unittest.main()


if __name__ == "__main__":
    main()
