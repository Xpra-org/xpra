#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock

from xpra.net.common import Packet
from xpra.net.constants import ConnectionMessage
from xpra.server.subsystem.network import NetworkServer


class FakeNetworkServer:

    def __init__(self):
        self.logged = []
        self.disconnect_protocol = Mock()

    def _disconnect_proto_info(self, _proto) -> str:
        return ""

    def _log_disconnect(self, _proto, fmt, *args) -> None:
        self.logged.append(fmt % args)


class NetworkServerTest(unittest.TestCase):

    def test_connection_close_is_cleaned(self):
        # this packet can be sent before authentication:
        server = FakeNetworkServer()
        proto = object()
        packet = Packet("connection-close", "done\x1b[2J‮", "line1\nline2", "x" * 10000)
        NetworkServer._process_connection_close(server, proto, packet)
        self.assertEqual(len(server.logged), 1)
        msg = server.logged[0]
        self.assertTrue(msg.startswith("client has requested disconnection: done[2J (line1 line2, xxx"))
        self.assertTrue(msg.isprintable())
        self.assertLess(len(msg), 1024)
        server.disconnect_protocol.assert_called_once_with(proto, ConnectionMessage.CLIENT_REQUEST)

    def test_connection_close_without_reason(self):
        server = FakeNetworkServer()
        NetworkServer._process_connection_close(server, None, Packet("connection-close"))
        self.assertEqual(server.logged, ["client has requested disconnection: "])


def main():
    unittest.main()


if __name__ == "__main__":
    main()
