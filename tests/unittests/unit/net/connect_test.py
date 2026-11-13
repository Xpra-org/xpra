#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import socket
import tempfile
import unittest

from xpra.os_util import POSIX


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


def main():
    unittest.main()


if __name__ == '__main__':
    main()
