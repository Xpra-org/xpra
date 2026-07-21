#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.net.socket_util import socket_connect
from xpra.scripts.config import InitException


class TestSocketConnect(unittest.TestCase):

    def test_invalid_port(self):
        for port in (-1, 0, 65536, 100000):
            with self.assertRaises(InitException):
                socket_connect("localhost", port)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
