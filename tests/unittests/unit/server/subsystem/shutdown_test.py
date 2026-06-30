#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.net.common import Packet
from xpra.net.constants import ConnectionMessage
from xpra.net.packet_type import SHUTDOWN_SERVER, EXIT_SERVER
from xpra.server import ServerExitMode
from xpra.server.subsystem.shutdown import ShutdownServer
from xpra.util.objects import typedict


class FakeServer:

    def __init__(self):
        self.hello_request_handlers = {}
        self.packet_handlers = {}
        self.cleanup_reasons = []
        self.quit_modes = []

    def add_packet_handler(self, packet_type: str, handler, main_thread=False) -> None:
        self.packet_handlers[packet_type] = (handler, main_thread)

    def cleanup_all_protocols(self, reason="") -> None:
        self.cleanup_reasons.append(reason)

    def clean_quit(self, exit_mode=ServerExitMode.NORMAL) -> None:
        self.quit_modes.append(exit_mode)


class ShutdownTest(unittest.TestCase):

    def setUp(self):
        self.server = FakeServer()
        self.shutdown = ShutdownServer(self.server)
        self.shutdown.init_packet_handlers()

    def test_handlers_and_features(self) -> None:
        self.assertEqual(set(self.server.hello_request_handlers), {"exit", "stop"})
        self.assertEqual(set(self.server.packet_handlers), {EXIT_SERVER, SHUTDOWN_SERVER})
        self.assertEqual(self.shutdown.get_server_features(), {"client-shutdown": self.shutdown.client_shutdown})

    def test_exit_request(self) -> None:
        with patch("xpra.server.subsystem.shutdown.GLib.timeout_add",
                   side_effect=lambda _delay, fn, *args: fn(*args)):
            self.server.packet_handlers[EXIT_SERVER][0](None, Packet(EXIT_SERVER, "restart"))
        self.assertEqual(self.server.cleanup_reasons, ["restart"])
        self.assertEqual(self.server.quit_modes, [ServerExitMode.EXIT])

    def test_stop_request(self) -> None:
        self.shutdown.client_shutdown = True
        with patch("xpra.server.subsystem.shutdown.GLib.timeout_add",
                   side_effect=lambda _delay, fn, *args: fn(*args)):
            handled = self.server.hello_request_handlers["stop"](None, typedict())
        self.assertTrue(handled)
        self.assertEqual(self.server.cleanup_reasons, [ConnectionMessage.SERVER_SHUTDOWN])
        self.assertEqual(self.server.quit_modes, [ServerExitMode.NORMAL])

    def test_disabled_stop_request(self) -> None:
        self.shutdown.client_shutdown = False
        handled = self.server.hello_request_handlers["stop"](None, typedict())
        self.assertFalse(handled)
        self.assertEqual(self.server.cleanup_reasons, [])
        self.assertEqual(self.server.quit_modes, [])


def main():
    unittest.main()


if __name__ == '__main__':
    main()
