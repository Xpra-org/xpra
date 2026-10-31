#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.client.subsystem.command import labelled_menu


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


def main():
    unittest.main()


if __name__ == "__main__":
    main()
