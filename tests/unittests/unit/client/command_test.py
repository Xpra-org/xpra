#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from xpra.client.base.command import AbstractImageXpraClient, CommandConnectClient, InfoXpraClient, StopXpraClient
from xpra.net.common import Packet
from xpra.net.packet_type import SHUTDOWN_SERVER
from xpra.exit_codes import ExitCode
from xpra.scripts.config import make_defaults_struct
from xpra.net.constants import MAX_PACKET_SIZE
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

    def test_info_allows_a_full_size_initial_response(self):
        protocol = SimpleNamespace(max_packet_size=16 * 1024)
        with patch.object(CommandConnectClient, "make_protocol", return_value=protocol):
            self.assertIs(InfoXpraClient.make_protocol(InfoXpraClient.__new__(InfoXpraClient), None), protocol)
        self.assertEqual(protocol.max_packet_size, MAX_PACKET_SIZE)

    def test_image_request_allows_a_full_size_initial_response(self):
        protocol = SimpleNamespace(max_packet_size=16 * 1024)
        with patch.object(CommandConnectClient, "make_protocol", return_value=protocol):
            self.assertIs(AbstractImageXpraClient.make_protocol(AbstractImageXpraClient.__new__(AbstractImageXpraClient), None), protocol)
        self.assertEqual(protocol.max_packet_size, MAX_PACKET_SIZE)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
