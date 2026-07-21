#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.net.common import Packet, BACKWARDS_COMPATIBLE
from xpra.net.constants import ConnectionMessage
from xpra.net.packet_type import SHUTDOWN_SERVER, EXIT_SERVER
from xpra.server import ServerExitMode
from xpra.server.subsystem.shutdown import ShutdownServer
from xpra.util.glib_scheduler import GLibScheduler
from xpra.util.objects import typedict


class FakeServer(GLibScheduler):
    """
    The subsystem copies its scheduler methods from the server it is
    constructed with, so run timers synchronously here to exercise
    the shutdown paths without a main loop.
    """

    def __init__(self):
        self.hello_request_handlers = {}
        self.packet_handlers = {}
        self.cleanup_reasons = []
        self.quit_modes = []

    def timeout_add(self, _delay: int, fn, *args) -> int:
        fn(*args)
        return 0

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
        # `exit-server` is only a separate packet in backwards-compatible mode,
        # otherwise it is folded into `shutdown-server`:
        expected = {SHUTDOWN_SERVER}
        if BACKWARDS_COMPATIBLE:
            expected.add(EXIT_SERVER)
        self.assertEqual(set(self.server.packet_handlers), expected)
        self.assertEqual(self.shutdown.get_server_features(), {"client-shutdown": self.shutdown.client_shutdown})

    def test_exit_request(self) -> None:
        if BACKWARDS_COMPATIBLE:
            self.server.packet_handlers[EXIT_SERVER][0](None, Packet(EXIT_SERVER, "restart"))
        else:
            # exit is requested via a `shutdown-server` packet with the exit flag set:
            self.server.packet_handlers[SHUTDOWN_SERVER][0](None, Packet(SHUTDOWN_SERVER, True, "restart"))
        self.assertEqual(self.server.cleanup_reasons, ["restart"])
        self.assertEqual(self.server.quit_modes, [ServerExitMode.EXIT])

    def test_shutdown_request(self) -> None:
        self.shutdown.client_shutdown = True
        # a `shutdown-server` packet without the exit flag requests a shutdown:
        self.server.packet_handlers[SHUTDOWN_SERVER][0](None, Packet(SHUTDOWN_SERVER))
        self.assertEqual(self.server.cleanup_reasons, [ConnectionMessage.SERVER_SHUTDOWN])
        self.assertEqual(self.server.quit_modes, [ServerExitMode.NORMAL])

    def test_stop_request(self) -> None:
        self.shutdown.client_shutdown = True
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
