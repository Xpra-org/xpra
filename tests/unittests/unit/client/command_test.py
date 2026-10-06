#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import io
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.client.base.command import AbstractImageXpraClient, CommandConnectClient, InfoXpraClient, RunClient, StopXpraClient
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

    def test_run_requests(self):
        for compatible in (False, True):
            for mode in ("run", "exec"):
                with self.subTest(compatible=compatible, mode=mode), \
                     patch("xpra.client.base.command.BACKWARDS_COMPATIBLE", compatible), \
                     patch.dict(os.environ, {"XPRA_RUN_WAIT_TIME": "1234"}), \
                     patch.object(CommandConnectClient, "make_hello_base", return_value={"base": True}), \
                     patch.object(CommandConnectClient, "make_hello", return_value={"full": True}):
                    client = RunClient(make_defaults_struct(), ["echo", "hello"], mode)
                    for hello in (client.make_hello_base(), client.make_hello()):
                        self.assertEqual(hello["request"], "exec" if mode == "exec" and not compatible else "run")
                        self.assertEqual(hello["run-wait-time"], 1234 if mode == "run" else 0)
                        self.assertEqual(hello["run"], ("echo", "hello"))

    def test_run_wait_default_and_zero(self):
        for value, expected in ((None, 5000), ("0", 0), ("-1", 0)):
            with patch.dict(os.environ):
                os.environ.pop("XPRA_RUN_WAIT_TIME", None)
                if value is not None:
                    os.environ["XPRA_RUN_WAIT_TIME"] = value
                self.assertEqual(RunClient(make_defaults_struct(), ["true"]).wait_time, expected)

    def test_run_output_and_exit_status(self):
        for mode, returncode, expected in (("run", 7, 7), ("run", -15, 143), ("run", None, 0), ("exec", None, 0)):
            with self.subTest(mode=mode, returncode=returncode):
                client = RunClient(make_defaults_struct(), ["test"], mode)
                client.quit = Mock()
                response = {"pid": 42}
                if mode == "run":
                    response.update({"stdout": b"out\x00\xff", "stderr": b"err\x00"})
                if returncode is not None:
                    response["returncode"] = returncode
                stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
                stderr = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
                with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
                    client.do_command(typedict({"run_response": response}))
                    stdout.flush()
                    stderr.flush()
                self.assertEqual(stdout.buffer.getvalue(), b"out\x00\xff" if mode == "run" else b"command started with pid 42\n")
                self.assertEqual(stderr.buffer.getvalue(), b"err\x00command started with pid 42\n" if mode == "run" else b"")
                client.quit.assert_called_once_with(expected)
                stdout.close()
                stderr.close()

    def test_run_old_server_errors_and_truncation(self):
        client = RunClient(make_defaults_struct(), ["test"])
        client.quit = Mock()
        client.warn_and_quit = Mock()
        with patch("sys.stderr", io.StringIO()) as output:
            client.do_command(typedict({"run_response": {"pid": 42, "stdout-truncated": True}}))
            self.assertIn("command stdout was truncated", output.getvalue())
        client.quit.assert_called_once_with(0)
        client.do_command(typedict({}))
        self.assertEqual(client.warn_and_quit.call_args.args[0], ExitCode.UNSUPPORTED)
        client.do_command(typedict({"run_response": {"code": 31, "message": "failed"}}))
        self.assertEqual(client.warn_and_quit.call_args.args[0], ExitCode.REMOTE_ERROR)

    def test_run_response_size_and_timers(self):
        with patch.dict(os.environ, {"XPRA_RUN_WAIT_TIME": "5000"}):
            client = RunClient(make_defaults_struct(), ["test"])
        protocol = SimpleNamespace(max_packet_size=16384, _conn=SimpleNamespace(timeout=20, connection_delay=2))
        with patch.object(CommandConnectClient, "make_protocol", return_value=protocol):
            self.assertIs(client.make_protocol(protocol._conn), protocol)
        self.assertEqual(protocol.max_packet_size, MAX_PACKET_SIZE)
        self.assertEqual(client.COMMAND_TIMEOUT, 6)
        client._protocol = protocol
        client.timeout_add = Mock(return_value=123)
        client.schedule_verify_connected()
        client.timeout_add.assert_called_once_with(28000, client.verify_connected)

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
