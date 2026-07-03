#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.client.base.command import StopXpraClient
from xpra.net.common import Packet
from xpra.net.packet_type import SHUTDOWN_SERVER
from xpra.exit_codes import ExitCode
from xpra.scripts.config import make_defaults_struct
from xpra.util.objects import typedict


class FakeProtocol:
    def __init__(self):
        self.closed = False

    def is_closed(self) -> bool:
        return self.closed

    def close(self) -> None:
        self.closed = True


class CommandClientTest(unittest.TestCase):

    def test_stop_client_accepts_startup_complete(self):
        client = StopXpraClient(make_defaults_struct())
        client.idle_add = lambda fn, *args: fn(*args)
        proto = FakeProtocol()
        packet = Packet("startup-complete")

        client.dispatch_packet(proto, packet, authenticated=True)

        self.assertFalse(proto.closed)
        self.assertEqual(client.completed_startup, packet)

    def test_stop_client_rejects_disabled_shutdown(self):
        client = StopXpraClient(make_defaults_struct())
        quit_codes = []
        timers = []
        client.quit = quit_codes.append
        client.timeout_add = lambda *args: timers.append(args)

        client.do_command(typedict({"client-shutdown": False}))

        self.assertEqual(quit_codes, [ExitCode.UNSUPPORTED])
        self.assertEqual(timers, [])

    def test_stop_client_schedules_fallback_shutdown(self):
        client = StopXpraClient(make_defaults_struct())
        timers = []
        sent = []
        client.timeout_add = lambda *args: timers.append(args) or len(timers)
        client.send = lambda *packet: sent.append(packet)

        client.do_command(typedict({"client-shutdown": True}))

        self.assertEqual(len(timers), 2)
        self.assertEqual(timers[0][0], 1000)
        self.assertEqual(timers[0][1], client.send_shutdown_server)
        self.assertEqual(timers[1][0], client.COMMAND_TIMEOUT * 1000)
        self.assertEqual(timers[1][1], client.timeout)
        timers[0][1](*timers[0][2:])
        self.assertEqual(sent, [(SHUTDOWN_SERVER,)])


def main():
    unittest.main()


if __name__ == '__main__':
    main()
