#!/usr/bin/env python3
# This file is part of Xpra.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.net.packet_type import PING_ECHO
from xpra.server.source import ping


class PingSourceTest(unittest.TestCase):

    def test_load_average_failure_does_not_drop_echo(self):
        connection = ping.PingConnection()
        connection.send_async = Mock()
        connection.statistics = SimpleNamespace(client_ping_latency=deque([(1, 0.025)]))
        with patch.object(ping, "PING_DETAILS", True), \
                patch.object(ping, "getloadavg", side_effect=OSError("load averages unavailable")):
            connection.process_ping(123, "source")
        connection.send_async.assert_called_once_with(PING_ECHO, 123, 0, 0, 0, 25, "source", will_have_more=False)

    def test_load_statistics_are_preserved_when_available(self):
        connection = ping.PingConnection()
        connection.send_async = Mock()
        with patch.object(ping, "PING_DETAILS", True), patch.object(ping, "getloadavg", return_value=(1, 2, 3)):
            connection.process_ping(123, "source")
        connection.send_async.assert_called_once_with(PING_ECHO, 123, 1, 2, 3, -1, "source", will_have_more=False)


if __name__ == "__main__":
    unittest.main()
