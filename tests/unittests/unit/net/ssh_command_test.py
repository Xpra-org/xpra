#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import asyncio
import io
import os
import socket
import sys
import unittest
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import paramiko

from xpra.net.ssh import exec_client
from xpra.net.ssh.command import copy_output
from xpra.net.ssh.paramiko import client as paramiko_client
from xpra.net.ssh.asyncssh import client as asyncssh_client


STDOUT = "LIVE session at :10 — 测试\n" * 8192
STDERR = "remote diagnostic\n" * 8192


class SSHCommandTest(unittest.TestCase):

    def test_text_output_split_utf8(self):
        data = iter((b"\xe6", b"\xb5\x8b", b""))
        output = io.StringIO()
        copy_output(lambda _n: next(data), output)
        self.assertEqual(output.getvalue(), "测")

    def test_external_command_drains_output_and_preserves_status(self):
        command = (
            "import sys\n"
            "sys.stderr.write('remote diagnostic\\n' * 8192)\n"
            "sys.stdout.write('LIVE session at :10 — 测试\\n' * 8192)\n"
            "raise SystemExit(17)\n"
        )
        desc = {
            "full_ssh": [sys.executable, "-c", command], "env": os.environ.copy(),
            "remote_xpra": ["xpra"], "proxy_command": ["list"], "display_as_args": [],
        }
        out, err = io.StringIO(), io.StringIO()
        with patch("sys.stdout", out), patch("sys.stderr", err):
            self.assertEqual(exec_client.run_command(desc), 17)
        self.assertEqual(out.getvalue(), STDOUT)
        self.assertEqual(err.getvalue(), STDERR)

    def test_paramiko_command_drains_both_streams_before_exit(self):
        server_sock, client_sock = socket.socketpair()
        server = paramiko.Transport(server_sock)
        client = paramiko.Transport(client_sock)
        self.addCleanup(server_sock.close)
        self.addCleanup(client_sock.close)
        self.addCleanup(server.close)
        self.addCleanup(client.close)
        server.add_server_key(paramiko.RSAKey.generate(1024))

        class CommandServer(paramiko.ServerInterface):
            @staticmethod
            def check_auth_none(_username):
                return paramiko.AUTH_SUCCESSFUL

            @staticmethod
            def check_channel_request(_kind, _chanid):
                return paramiko.OPEN_SUCCEEDED

            @staticmethod
            def check_channel_exec_request(channel, _command):
                def send():
                    channel.sendall_stderr(STDERR.encode())
                    channel.sendall(STDOUT.encode())
                    channel.send_exit_status(17)
                    channel.close()
                Thread(target=send, daemon=True).start()
                return True

        server.start_server(event=Event(), server=CommandServer())
        client.start_client(timeout=5)
        client.auth_none("testuser")
        channel = client.open_session(window_size=32768, timeout=5)
        channel.exec_command("xpra list")
        conn = MagicMock(_socket=channel)
        conn.close.side_effect = channel.close
        out, err = io.StringIO(), io.StringIO()
        with patch.object(paramiko_client, "connect_to", return_value=conn), patch("sys.stdout", out), patch("sys.stderr", err):
            self.assertEqual(paramiko_client.run_command({}), 17)
        self.assertEqual(out.getvalue(), STDOUT)
        self.assertEqual(err.getvalue(), STDERR)
        self.assertFalse(client.is_active())

    def test_asyncssh_command_drains_both_streams_before_exit(self):
        class Loop:
            @staticmethod
            def sync(fn):
                return asyncio.run(fn())

        stdout = SimpleNamespace(read=AsyncMock(side_effect=[STDOUT.encode(), b""]))
        stderr = SimpleNamespace(read=AsyncMock(side_effect=[STDERR.encode(), b""]))
        process = SimpleNamespace(stdout=stdout, stderr=stderr, stdin=MagicMock(), returncode=17, wait_closed=AsyncMock())
        conn = SimpleNamespace(_process=process, _async_close=AsyncMock())
        out, err = io.StringIO(), io.StringIO()
        with patch.object(asyncssh_client, "connect_to", return_value=conn), \
                patch.object(asyncssh_client, "get_threaded_loop", return_value=Loop()), \
                patch("sys.stdout", out), patch("sys.stderr", err):
            self.assertEqual(asyncssh_client.run_command({}), 17)
        self.assertEqual(out.getvalue(), STDOUT)
        self.assertEqual(err.getvalue(), STDERR)
        conn._async_close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
