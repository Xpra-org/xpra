#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Systemd socket activation, exercised for real:
a child process places listening sockets at fd 3+ and sets `LISTEN_FDS` / `LISTEN_PID`,
exactly like systemd does, then runs the real lookup code.
Everything runs in a child process because the fd numbers are fixed by the protocol,
and taking them over in the test runner would clobber whatever it has open there.
"""

import os
import sys
import json
import socket
import tempfile
import unittest
import subprocess

from xpra.os_util import POSIX, OSX

try:
    from xpra.platform.posix import sd_listen
except ImportError:
    sd_listen = None


CHILD_SCRIPT = r"""
import os
import sys
import json
import fcntl
import socket

specs = json.loads(sys.argv[1])
api = sys.argv[2]

# create the listening sockets, then move them to fd 3, 4, ...
# going through high fds first so that we never overwrite one of our own sockets:
high_fds = []
for spec in specs:
    if spec == "unix":
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(sys.argv[3])
    elif spec == "inet6":
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        sock.bind(("::1", 0))
    else:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    high_fds.append(fcntl.fcntl(sock.fileno(), fcntl.F_DUPFD, 100))
    sock.close()
for i, fd in enumerate(high_fds):
    os.dup2(fd, 3 + i)
    os.close(fd)

os.environ["LISTEN_PID"] = str(os.getpid())
os.environ["LISTEN_FDS"] = str(len(specs))

results = []
if api == "create_sockets":
    from xpra.net.socket_util import create_sockets
    for listener in create_sockets({}, sd_listen=True):
        results.append((listener.socktype, listener.socket.family, listener.address))
else:
    from xpra.platform.posix.sd_listen import get_sd_listen_sockets
    for socktype, sock, addr in get_sd_listen_sockets():
        results.append((socktype, sock.family, addr))
print(json.dumps(results))
"""


@unittest.skipUnless(POSIX and not OSX, "systemd socket activation is linux only")
@unittest.skipIf(sd_listen is None, "sd_listen module not built")
class SDListenTest(unittest.TestCase):

    def run_child(self, specs: list[str], api="get_sd_listen_sockets", env=None) -> list:
        child_env = {k: v for k, v in os.environ.items() if not k.startswith(("XPRA_SD", "LISTEN_"))}
        child_env.update(env or {})
        with tempfile.TemporaryDirectory() as tmpdir:
            sockpath = os.path.join(tmpdir, "sd-socket")
            cmd = [sys.executable, "-c", CHILD_SCRIPT, json.dumps(specs), api, sockpath]
            proc = subprocess.run(cmd, env=child_env, capture_output=True, text=True, timeout=30)
            if proc.returncode != 0:
                raise RuntimeError(f"child failed with exit code {proc.returncode}:\n{proc.stdout}\n{proc.stderr}")
            results = json.loads(proc.stdout.splitlines()[-1])
            for result in results:
                if result[0] == "socket":
                    assert result[2] == sockpath, f"expected {sockpath!r} but got {result[2]!r}"
            return results

    def test_no_sockets(self):
        assert self.run_child([]) == []

    def test_unix(self):
        results = self.run_child(["unix"])
        assert len(results) == 1
        socktype, family, _ = results[0]
        assert socktype == "socket"
        assert family == socket.AF_UNIX

    def test_inet(self):
        results = self.run_child(["inet"])
        assert len(results) == 1
        socktype, family, addr = results[0]
        assert socktype == "tcp"
        assert family == socket.AF_INET
        assert addr[0] == "127.0.0.1" and addr[1] > 0

    def test_inet6(self):
        if not socket.has_ipv6:
            self.skipTest("no IPv6 support")
        try:
            with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as s:
                s.bind(("::1", 0))
        except OSError:
            self.skipTest("cannot bind to IPv6 loopback")
        results = self.run_child(["inet6"])
        assert len(results) == 1
        socktype, family, addr = results[0]
        assert socktype == "tcp"
        assert family == socket.AF_INET6
        assert addr[0] == "::1"

    def test_socket_type_env(self):
        results = self.run_child(["inet", "inet"], env={"XPRA_SD_SOCKET_TYPE": "ws"})
        assert [r[0] for r in results] == ["ws", "ws"]

    def test_per_fd_socket_type(self):
        # the second socket is fd 4:
        results = self.run_child(["inet", "inet"], env={"XPRA_SD_SOCKET_TYPE": "ws", "XPRA_SD4_SOCKET_TYPE": "ssl"})
        assert [r[0] for r in results] == ["ws", "ssl"]

    def test_invalid_socket_type(self):
        results = self.run_child(["inet"], env={"XPRA_SD_SOCKET_TYPE": "invalid"})
        assert [r[0] for r in results] == ["tcp"]

    def test_mixed(self):
        results = self.run_child(["inet", "unix", "inet"])
        assert [r[0] for r in results] == ["tcp", "socket", "tcp"]

    def test_create_sockets(self):
        # the code path used by the server:
        results = self.run_child(["inet", "unix"], api="create_sockets", env={"XPRA_SD3_SOCKET_TYPE": "wss"})
        assert [(r[0], r[1]) for r in results] == [("wss", socket.AF_INET), ("socket", socket.AF_UNIX)]


def main():
    unittest.main()


if __name__ == '__main__':
    main()
