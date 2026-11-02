#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""The tray widget sends its geometry through the window subsystem, in server coordinates."""

import unittest
from types import SimpleNamespace

from xpra.net.packet_type import WINDOW_CONFIGURE
from xpra.client.gui.client_tray import ClientTray


class FakeTrayWidget:

    @staticmethod
    def get_geometry():
        return 10, 20, 32, 16

    @staticmethod
    def get_orientation():
        return "horizontal"


def make_tray(subsystems: dict) -> ClientTray:
    # skip the constructor: it creates a backing and schedules the first configure
    tray = ClientTray.__new__(ClientTray)
    tray.wid = 5
    tray.tray_widget = FakeTrayWidget()
    tray._geometry = None
    tray._size = (32, 16)
    tray.get_subsystem = subsystems.get
    return tray


class ClientTrayTest(unittest.TestCase):

    def test_reconfigure(self) -> None:
        sent = []
        subsystems = {
            "window": SimpleNamespace(send=lambda *args: sent.append(args)),
            "display": SimpleNamespace(crect=lambda x, y, w, h: (x * 2, y * 2, w * 2, h * 2)),
        }
        tray = make_tray(subsystems)
        tray.reconfigure()
        self.assertEqual(len(sent), 1)
        packet_type, wid, attrs = sent[0]
        self.assertEqual(packet_type, WINDOW_CONFIGURE)
        self.assertEqual(wid, 5)
        self.assertEqual(attrs["geometry"], (20, 40, 64, 32))
        self.assertEqual(attrs["properties"]["orientation"], "horizontal")
        # unchanged geometry is not sent again, unless forced:
        tray.reconfigure()
        self.assertEqual(len(sent), 1)
        tray.send_configure()
        self.assertEqual(len(sent), 2)

    def test_no_subsystems(self) -> None:
        tray = make_tray({})
        tray.reconfigure()
        self.assertEqual(tray._geometry, (10, 20, 32, 16))


def main():
    unittest.main()


if __name__ == '__main__':
    main()
