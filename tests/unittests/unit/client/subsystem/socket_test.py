#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.client.base.control import Control
from xpra.client.subsystem.socket import NetworkListener
from xpra.exit_codes import ExitCode
from xpra.util.objects import typedict


class FakeClient:
    """ minimal stand-in for the owning client (see `StubClientSubsystem.get_subsystem`) """

    def __init__(self):
        self.exit_code = None
        self.subsystems: dict[str, object] = {}

    @staticmethod
    def idle_add(fn, *args) -> int:
        fn(*args)
        return 0

    timeout_add = idle_add

    @staticmethod
    def source_remove(_tid: int) -> None:
        """ nothing to remove: `idle_add` above runs synchronously """


class TestNetworkListener(unittest.TestCase):

    def test_control_disabled(self):
        listener = NetworkListener(FakeClient())
        proto = SimpleNamespace(_conn=SimpleNamespace(options={}), send_now=Mock())
        caps = typedict({"command_request": ("debug", "disable", "all")})
        self.assertTrue(listener.handle_hello_request(proto, "command", caps))
        proto.send_now.assert_called_once()
        packet = proto.send_now.call_args.args[0]
        self.assertEqual(packet.get_type(), "hello")
        code, response = packet.get_dict(1)["command_response"]
        self.assertEqual(code, ExitCode.UNSUPPORTED)
        self.assertIn("disabled", response)
        self.assertIn("--control=yes", response)

    def test_control_enabled(self):
        client = FakeClient()
        control = client.subsystems["control"] = Control(client)
        control.parse_server_capabilities(typedict())
        listener = NetworkListener(client)
        proto = SimpleNamespace(_conn=SimpleNamespace(options={}), send_now=Mock())
        caps = typedict({"command_request": ("debug", "status")})
        self.assertTrue(listener.handle_hello_request(proto, "command", caps))
        proto.send_now.assert_called_once()
        packet = proto.send_now.call_args.args[0]
        self.assertEqual(packet.get_type(), "hello")
        code, response = packet.get_dict(1)["command_response"]
        self.assertEqual(code, ExitCode.OK)
        self.assertTrue(response.startswith("logging is enabled for:"), response)

    def test_run_twice_listens_once(self):
        # starting a named-pipe listener twice fails with "threads can only be started once":
        listener = NetworkListener(FakeClient())
        listener.sockets = [SimpleNamespace(socktype="named-pipe", socket=None, address="\\\\.\\pipe\\Xpra\\1")]
        with patch("xpra.client.subsystem.socket.start_thread", side_effect=lambda fn, *a, **kw: fn()), \
                patch("xpra.client.subsystem.socket.sleep"), \
                patch("xpra.client.subsystem.socket.add_listen_socket") as add_listen_socket:
            listener.run()
            listener.run()
        add_listen_socket.assert_called_once()


def main():
    unittest.main()


if __name__ == '__main__':
    main()
