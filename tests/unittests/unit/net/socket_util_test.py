#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.net import socket_util
from xpra.net.socket_util import socket_connect, socket_fast_read
from xpra.scripts.config import InitException


class TestSocketConnect(unittest.TestCase):

    def test_invalid_port(self):
        for port in (-1, 0, 65536, 100000):
            with self.assertRaises(InitException):
                socket_connect("localhost", port)


class TestSocketFastRead(unittest.TestCase):

    def test_legacy_socket_timeout_retries(self):
        class LegacySocketTimeout(OSError):
            pass

        class Connection:
            def __init__(self):
                self._socket = self
                self.can_retry = self.retry
                self.read_count = 0

            def retry(self, _error):
                return True

            def settimeout(self, _timeout):
                pass

            def read(self, _size):
                self.read_count += 1
                if self.read_count == 1:
                    raise LegacySocketTimeout()
                return b"x"

        conn = Connection()
        original_can_retry = conn.can_retry
        with patch.object(socket_util.socket, "timeout", LegacySocketTimeout):
            self.assertEqual(socket_fast_read(conn), b"x")
        self.assertEqual(conn.read_count, 2)
        self.assertIs(conn.can_retry, original_can_retry)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
