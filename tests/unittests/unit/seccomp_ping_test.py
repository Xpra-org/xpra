#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Ping echoes survive when the parse filter forbids reading the load average."""

import os
import subprocess
import sys
import textwrap
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.net.common import Packet
from xpra.net.packet_type import PING_ECHO
from xpra.os_util import LINUX
from xpra.seccomp import glibc, parse


class SeccompPingTest(unittest.TestCase):

    @unittest.skipUnless(LINUX, "glibc version detection requires Linux")
    def test_glibc_version(self):
        for value, expected in (("glibc 2.34", (2, 34)), ("glibc 2.35", (2, 35)),
                                ("glibc 2.34.9000", (2, 34, 9000)), ("musl 1.2.5", ()),
                                (None, ()), ("unknown", ()), ("glibc invalid", ())):
            with self.subTest(value=value), patch.object(glibc.os, "confstr", return_value=value):
                self.assertEqual(glibc.get_version(), expected)
        for error in (OSError(), ValueError()):
            with self.subTest(error=type(error)), patch.object(glibc.os, "confstr", side_effect=error):
                self.assertEqual(glibc.get_version(), ())

    def test_disabled_filter_does_not_query_libc(self):
        with patch.object(parse, "is_enabled", return_value=False), patch.object(glibc, "get_version") as version:
            self.assertFalse(parse.blocks_getloadavg())
        version.assert_not_called()

    def test_loadavg_policy(self):
        for version, blocked in (((2, 17), True), ((2, 34), True), ((2, 34, 9000), True),
                                 ((2, 35), False), ((2, 36), False), ((), False)):
            with self.subTest(version=version), patch.object(parse, "is_enabled", return_value=True), \
                    patch.object(glibc, "get_version", return_value=version):
                self.assertEqual(parse.blocks_getloadavg(), blocked)

    def test_startup_guard(self):
        # Each subprocess imports the ping modules with its own startup policy.
        script = textwrap.dedent("""
            import sys
            from unittest.mock import patch
            enabled, minor, expected = map(int, sys.argv[1:])
            with patch('xpra.seccomp.parse.is_enabled', return_value=bool(enabled)), \
                    patch('xpra.seccomp.glibc.get_version', return_value=(2, minor)):
                from xpra.client.subsystem import ping as client
                from xpra.server.source import ping as server
            assert client.PING_LOAD == bool(expected), client.PING_LOAD
            assert server.PING_LOAD == bool(expected), server.PING_LOAD
        """)
        for enabled, minor, expected in ((1, 34, 0), (1, 35, 1), (0, 34, 1)):
            with self.subTest(enabled=enabled, minor=minor):
                result = subprocess.run(
                    [sys.executable, "-c", script, str(enabled), str(minor), str(expected)],
                    env=dict(os.environ, XPRA_PING_DETAILS="1"), capture_output=True, text=True, timeout=20,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_echoes_keep_latency_when_load_is_unavailable(self):
        from xpra.client.subsystem import ping as client_ping
        from xpra.server.source import ping as server_ping
        for allowed, error in ((False, False), (True, False), (True, True)):
            with self.subTest(allowed=allowed, error=error):
                client = SimpleNamespace(server_latency=[(0, 0.125)], send=Mock())
                source = SimpleNamespace(statistics=SimpleNamespace(client_ping_latency=[(0, 0.25)]), send_async=Mock())
                kwargs = {"side_effect": PermissionError()} if error else {"return_value": (123, 456, 789)}
                with patch.object(client_ping, "PING_LOAD", allowed), patch.object(client_ping, "SWALLOW_PINGS", False), \
                        patch.object(server_ping, "PING_LOAD", allowed), patch.object(server_ping, "PING_DETAILS", True), \
                        patch.object(client_ping, "getloadavg", **kwargs) as client_load, \
                        patch.object(server_ping, "getloadavg", **kwargs) as server_load:
                    client_ping.PingClient._process_ping(client, Packet("ping", 42, 0, "source"))
                    server_ping.PingConnection.process_ping(source, 42, "source")
                if allowed:
                    client_load.assert_called_once_with()
                    server_load.assert_called_once_with()
                else:
                    client_load.assert_not_called()
                    server_load.assert_not_called()
                load = (123, 456, 789) if allowed and not error else (0, 0, 0)
                client.send.assert_called_once_with(PING_ECHO, 42, *load, 125, "source")
                source.send_async.assert_called_once_with(PING_ECHO, 42, *load, 250, "source", will_have_more=False)


if __name__ == "__main__":
    unittest.main()
