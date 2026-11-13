#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import socket
import tempfile
import unittest
from unittest.mock import patch

from xpra.os_util import POSIX, LINUX


@unittest.skipUnless(POSIX, "unix domain sockets are only used on posix")
class ConnectToSocketTest(unittest.TestCase):

    def test_filename_is_the_path_we_connected_to(self):
        from xpra.net.connect import connect_to_socket
        with tempfile.TemporaryDirectory() as tmpdir:
            # the server binds to a path which we reach through another one,
            # like a socket bind mounted in a container:
            real = os.path.join(tmpdir, "real")
            os.mkdir(real)
            os.symlink(real, os.path.join(tmpdir, "link"))
            server = socket.socket(socket.AF_UNIX)
            server.bind(os.path.join(real, "socket"))
            server.listen(1)
            sockpath = os.path.join(tmpdir, "link", "socket")
            conn = connect_to_socket({
                "display_name": "",
                "socket_path": sockpath,
                "timeout": 5,
            })
            try:
                self.assertEqual(conn.filename, sockpath)
            finally:
                conn.close()
                server.close()

    @unittest.skipUnless(LINUX, "abstract sockets are only available on Linux")
    def test_abstract_socket_can_be_skipped(self):
        # a proxy server running as root must not use the abstract socket of another user's session,
        # the session's `peercred` authentication would reject it:
        from xpra.net.connect import connect_to_socket, ABSTRACT_SOCKET_PREFIX
        display = 60000 + os.getpid() % 5000
        abstract = socket.socket(socket.AF_UNIX)
        try:
            abstract.bind(f"\0{ABSTRACT_SOCKET_PREFIX}{display}")
        except OSError as e:
            abstract.close()
            self.skipTest(f"cannot bind abstract socket for display {display}: {e}")
        abstract.listen(1)
        with tempfile.TemporaryDirectory() as tmpdir:
            sockpath = os.path.join(tmpdir, "socket")
            server = socket.socket(socket.AF_UNIX)
            server.bind(sockpath)
            server.listen(1)
            try:
                for skip, expected in ((False, f"@{ABSTRACT_SOCKET_PREFIX}{display}"), (True, sockpath)):
                    with self.subTest(skip=skip):
                        desc = {"display_name": f":{display}", "display": str(display), "timeout": 5}
                        if skip:
                            desc["abstract-socket"] = False
                        with patch("xpra.scripts.picker.get_sockpath", return_value=sockpath):
                            conn = connect_to_socket(desc)
                        try:
                            self.assertEqual(conn.filename, expected)
                        finally:
                            conn.close()
            finally:
                server.close()
                abstract.close()


def main():
    unittest.main()


if __name__ == '__main__':
    main()
