#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock, patch

from xpra.client.gui.ui_client_base import UIXpraClient, labelled_menu
from xpra.util import typedict


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

    def test_initial_menu(self):
        client = UIXpraClient.__new__(UIXpraClient)
        client.session_name = ""
        client.request_start = ()
        client.request_start_child = ()
        client._remote_platform = ""
        client._remote_version = ()
        client._remote_revision = 0
        menu = {"Accessories": {"Entries": {"org.gnome.Calculator": {"Name": "Calculator"}}}}
        with patch.multiple("xpra.client.gui.ui_client_base", CLIENT_BASES=(), set_name=Mock()):
            self.assertTrue(client.parse_server_capabilities(typedict({
                "start-new-commands": True, "xdg-menu": menu,
            })))
        self.assertEqual(client.server_xdg_menu["Accessories"]["Entries"], {
            "Calculator": {"Name": "Calculator"},
        })

    def test_menu_update(self):
        client = UIXpraClient.__new__(UIXpraClient)
        client._on_server_setting_changed = {}
        callback = Mock()
        client.on_server_setting_changed("xdg-menu", callback)
        menu = {"Accessories": {"Entries": {"nemo": {"Name": "Files", "command": "nemo"}}}}
        client._process_setting_change(("setting-change", b"xdg-menu", menu))
        self.assertEqual(client.server_xdg_menu["Accessories"]["Entries"], {
            "Files": {"Name": "Files", "command": "nemo"},
        })
        callback.assert_called_once_with("xdg-menu", client.server_xdg_menu)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
