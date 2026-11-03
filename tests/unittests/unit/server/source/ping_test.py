#!/usr/bin/env python3
# This file is part of Xpra.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.net.packet_type import PING_ECHO
from xpra.net.common import parse_thread_getloadavg
from xpra.seccomp import glibc as seccomp_glibc
from xpra.seccomp import parse as seccomp_parse
from xpra.server.source import ping


class PingSourceTest(unittest.TestCase):

    def test_load_average_failure_does_not_drop_echo(self):
        connection = ping.PingConnection()
        connection.init_state()
        connection.send_async = Mock()
        connection.statistics = SimpleNamespace(client_ping_latency=deque([(1, 0.025)]))
        with patch.object(ping, "PING_DETAILS", True), patch.object(ping, "PING_LOAD", True), \
                patch.object(ping, "getloadavg", side_effect=OSError("load averages unavailable")) as getloadavg:
            connection.process_ping(123, "source")
        getloadavg.assert_called_once_with()
        connection.send_async.assert_called_once_with(PING_ECHO, 123, 0, 0, 0, 25, "source", will_have_more=False)

    def test_packet_echo_skips_blocked_load_and_preserves_latency(self):
        connection = ping.PingConnection()
        connection.init_state()
        connection.send_async = Mock()
        connection.statistics = SimpleNamespace(client_ping_latency=deque([(1, 0.025)]))
        with patch.object(ping, "PING_DETAILS", True), patch.object(ping, "PING_LOAD", False), \
                patch.object(ping, "getloadavg", side_effect=AssertionError("packet thread syscall")) as getloadavg:
            connection.process_ping(123, "source")
        getloadavg.assert_not_called()
        connection.send_async.assert_called_once_with(PING_ECHO, 123, 0, 0, 0, 25, "source", will_have_more=False)

    def test_load_statistics_are_preserved_when_available(self):
        connection = ping.PingConnection()
        connection.init_state()
        connection.send_async = Mock()
        with patch.object(ping, "PING_DETAILS", True), patch.object(ping, "PING_LOAD", True), \
                patch.object(ping, "getloadavg", return_value=(1, 2, 3)) as getloadavg:
            connection.process_ping(123, "source")
        getloadavg.assert_called_once_with()
        connection.send_async.assert_called_once_with(PING_ECHO, 123, 1, 2, 3, -1, "source", will_have_more=False)

    def test_disabled_details_still_echo(self):
        connection = ping.PingConnection()
        connection.init_state()
        connection.send_async = Mock()
        connection.statistics = SimpleNamespace(client_ping_latency=deque([(1, 0.025)]))
        with patch.object(ping, "PING_DETAILS", False), patch.object(ping, "PING_LOAD", False), \
                patch.object(ping, "getloadavg") as getloadavg:
            connection.process_ping(123, "source")
        getloadavg.assert_not_called()
        connection.send_async.assert_called_once_with(PING_ECHO, 123, 0, 0, 0, -1, "source", will_have_more=False)

    def test_parse_load_policy(self):
        for enabled, version, allowed in (
                (True, (2, 34), False),
                (True, (2, 35), True),
                (True, (2, 43), True),
                (False, (2, 34), True),
                (True, (), True),
        ):
            with self.subTest(enabled=enabled, version=version), \
                    patch.object(seccomp_parse, "is_enabled", return_value=enabled), \
                    patch.object(seccomp_glibc, "get_version", return_value=version):
                self.assertEqual(parse_thread_getloadavg(), allowed)


if __name__ == "__main__":
    unittest.main()
