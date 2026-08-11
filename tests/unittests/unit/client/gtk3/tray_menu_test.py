#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest


class TrayMenuTest(unittest.TestCase):

    def test_start_menu_checksum_includes_icons(self):
        from xpra.client.gtk3.tray_menu import start_menu_checksum
        menu = {
            "Utilities": {
                "IconData": b"category-one",
                "IconType": "png",
                "Entries": {
                    "Editor": {
                        "command": "editor",
                        "IconData": b"icon-one",
                        "IconType": "png",
                    },
                },
            },
        }
        checksum = start_menu_checksum(menu)
        menu["Utilities"]["Entries"]["Editor"]["IconData"] = b"icon-two"
        assert start_menu_checksum(menu) != checksum


def main():
    unittest.main()


if __name__ == "__main__":
    main()
