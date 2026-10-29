#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Cross-side interaction test: wires the client `PingClient` subsystem to the
server `PingServer` subsystem (+ `PingConnection` source) and verifies a real
ping/echo round-trip in both directions.
"""

import unittest
from time import monotonic

from xpra.util.objects import AdHocStruct
from xpra.net.packet_type import PING_ECHO

from unit.loopback_util import LoopbackTest


def _opts():
    opts = AdHocStruct()
    opts.pings = 1
    return opts


class PingLoopbackTest(LoopbackTest):

    def _connect(self):
        from xpra.client.subsystem.ping import PingClient
        from xpra.server.subsystem.ping import PingServer
        from xpra.server.source.ping import PingConnection
        return self.connect(PingClient, PingServer, PingConnection,
                            client_opts=_opts(), server_opts=_opts(),
                            caps={"ping": True})

    def test_client_ping_echoed_by_server(self):
        client, _server, _source = self._connect()
        client.send_ping()
        # the client sent a "ping" to the server:
        self.assertTrue(self.c2s, "client did not send anything")
        self.assertEqual(self.c2s[0][0], "ping")
        ping_time = self.c2s[0][1]
        # the server echoed it back using the mode's packet name:
        self.assertTrue(any(p[0] == PING_ECHO for p in self.s2c),
                        "server did not echo the ping: %s" % (self.s2c,))
        # and the client recorded the echo:
        self.assertEqual(client.last_echoed_time, ping_time)
        self.assertEqual(len(client.server_latency), 1)

    def test_server_ping_echoed_by_client(self):
        _client, _server, source = self._connect()
        # PingConnection.ping() only fires once the hello has been sent
        # and at least 5s have elapsed:
        source.hello_sent = monotonic() - 10
        source.ping()
        # the server sent a "ping" to the client:
        self.assertTrue(any(p[0] == "ping" for p in self.s2c),
                        "server did not send a ping: %s" % (self.s2c,))
        ping_time = next(p[1] for p in self.s2c if p[0] == "ping")
        # the client echoed it back using the mode's packet name:
        self.assertTrue(any(p[0] == PING_ECHO for p in self.c2s),
                        "client did not echo the ping: %s" % (self.c2s,))
        # and the server processed the echo:
        self.assertEqual(source.last_ping_echoed_time, ping_time)

    def test_pings_carry_sid(self):
        client, _server, source = self._connect()
        client.send_ping()
        self.assertEqual(self.c2s[0][3], client.uuid)
        echo = next(p for p in self.s2c if p[0] == PING_ECHO)
        self.assertEqual(echo[6], client.uuid)
        source.hello_sent = monotonic() - 10
        source.ping()
        ping = next(p for p in self.s2c if p[0] == "ping")
        self.assertEqual(ping[3], source.ping_uuid)
        echo = next(p for p in self.c2s if p[0] == PING_ECHO)
        self.assertEqual(echo[6], source.ping_uuid)

    def test_client_ignores_foreign_echo(self):
        from xpra.net.common import Packet
        client, _server, _source = self._connect()
        client._process_echo(Packet(PING_ECHO, 1000, 0, 0, 0, -1, "not-ours"))
        self.assertEqual(client.last_echoed_time, 0)
        self.assertEqual(len(client.server_latency), 0)
        # so are echoes without a sid:
        client._process_echo(Packet(PING_ECHO, 2000, 0, 0, 0, -1))
        client._process_echo(Packet(PING_ECHO, 3000, 0, 0, 0, -1, ""))
        self.assertEqual(client.last_echoed_time, 0)
        client._process_echo(Packet(PING_ECHO, 4000, 0, 0, 0, -1, client.uuid))
        self.assertEqual(client.last_echoed_time, 4000)
        self.assertEqual(len(client.server_latency), 1)

    def test_server_ignores_foreign_echo(self):
        from xpra.net.common import Packet
        _client, _server, source = self._connect()
        source.process_ping_echo(Packet(PING_ECHO, 1000, 0, 0, 0, -1, "not-ours"))
        self.assertEqual(source.last_ping_echoed_time, 0)
        source.process_ping_echo(Packet(PING_ECHO, 2000, 0, 0, 0, -1))
        self.assertEqual(source.last_ping_echoed_time, 0)
        source.process_ping_echo(Packet(PING_ECHO, 3000, 0, 0, 0, -1, source.ping_uuid))
        self.assertEqual(source.last_ping_echoed_time, 3000)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
