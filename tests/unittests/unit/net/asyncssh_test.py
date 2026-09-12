#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import asyncio
import os
import tempfile
import unittest
from unittest.mock import patch

from xpra.net.ssh.asyncssh.client import HostKeyManager, build_remote_command, host_key_name
from xpra.net.ssh.asyncssh.connection import SSHStreamConnection


class FakeLoop:
    @staticmethod
    def sync(async_fn, *args):
        return asyncio.run(async_fn(*args))

    @staticmethod
    def call(coro) -> None:
        asyncio.run(coro)


class FakeReader:
    def __init__(self, data: bytes):
        self.data = data

    async def read(self, n: int) -> bytes:
        data = self.data[:n]
        self.data = self.data[n:]
        return data


class FakeWriter:
    def __init__(self):
        self.data = bytearray()
        self.closed = False

    def write(self, data: bytes) -> None:
        self.data.extend(data)

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        pass


class FakeSSHConnection:
    def __init__(self):
        self.closed = False

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        pass

    @staticmethod
    def get_extra_info(name: str, default=None):
        return {
            "client_version": "client",
            "server_version": "server",
            "peername": ("host", 22),
        }.get(name, default)


class FakeKey:
    @staticmethod
    def get_algorithm() -> str:
        return "ssh-ed25519"

    @staticmethod
    def export_public_key(_format_name: str) -> bytes:
        return b"ssh-ed25519 NEW"


class AsyncSSHTest(unittest.TestCase):

    def test_stream_connection(self):
        reader = FakeReader(b"response")
        writer = FakeWriter()
        ssh_connection = FakeSSHConnection()
        connection = SSHStreamConnection(
            FakeLoop(), reader, writer, ssh_connection, ("host", 22)
        )
        assert connection.read(4) == b"resp"
        assert connection.read(8) == b"onse"
        assert connection.write(memoryview(b"request")) == 7
        assert writer.data == b"request"
        assert connection.input_bytecount == 8
        assert connection.output_bytecount == 7
        assert connection.get_info()["asyncssh"]["server-version"] == "server"
        connection.close()
        assert writer.closed
        assert ssh_connection.closed

    def test_remote_command(self):
        command = build_remote_command(
            "xpra", ["_proxy"], ["/run/user/1000/xpra"], [":10"]
        )
        assert command == (
            '"xpra" "_proxy" "--socket-dirs=/run/user/1000/xpra" ":10"'
        )
        assert host_key_name("host", 22) == "host"
        assert host_key_name("host", 2222) == "[host]:2222"

    def test_replace_host_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "known_hosts")
            with open(filename, "wb") as known_hosts:
                known_hosts.write(b"[host]:2222,other ssh-ed25519 OLD\n")
            with patch(
                    "xpra.net.ssh.asyncssh.client.get_ssh_known_hosts_files",
                    return_value=[filename]):
                HostKeyManager.save("host", "192.0.2.1", 2222, FakeKey(), replace=True)
            with open(filename, "rb") as known_hosts:
                assert known_hosts.readlines() == [
                    b"other ssh-ed25519 OLD\n",
                    b"[host]:2222 ssh-ed25519 NEW\n",
                ]


def main():
    unittest.main()


if __name__ == "__main__":
    main()
