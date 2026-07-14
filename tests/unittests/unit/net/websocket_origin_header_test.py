#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.net.http.common import check_origin
from xpra.net.websockets.headers import origin


class TestWebsocketOriginHeader(unittest.TestCase):

    def test_auto_origin(self):
        headers = origin.get_headers("localhost", 14500)
        assert headers[b"Origin"] == b"http://localhost:14500"
        # the default headers must be included, so this module can be used on its own:
        assert headers[b"Host"] == b"localhost:14500"
        assert headers[b"Upgrade"] == b"websocket"

    def test_auto_origin_without_port(self):
        headers = origin.get_headers("desktop.example", 0)
        assert headers[b"Origin"] == b"http://desktop.example"

    def test_explicit_origin(self):
        with patch.object(origin, "ORIGIN", "https://desktop.example"):
            headers = origin.get_headers("localhost", 14500)
        assert headers[b"Origin"] == b"https://desktop.example"

    def test_no_origin(self):
        with patch.object(origin, "ORIGIN", ""):
            headers = origin.get_headers("localhost", 14500)
        assert b"Origin" not in headers

    def test_accepted_by_a_strict_server(self):
        # what we send must satisfy the servers we can connect to:
        for host, port in (("localhost", 14500), ("desktop.example", 443)):
            headers = origin.get_headers(host, port)
            sent = headers[b"Origin"].decode()
            for policy in ("auto", "strict", "auto,strict"):
                assert check_origin(sent, f"{host}:{port}", policy), f"{sent!r} rejected by {policy!r}"


def main():
    unittest.main()


if __name__ == '__main__':
    main()
