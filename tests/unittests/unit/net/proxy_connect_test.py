#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

try:
    import socks
except ImportError:
    socks = None


@unittest.skipUnless(socks, "PySocks is required")
class TestProxyConnect(unittest.TestCase):

    def test_destination(self) -> None:
        from xpra.net.socket_util import proxy_connect
        with patch("socks.socksocket") as socksocket:
            proxy_connect({
                "type": "tcp", "host": "server.example", "port": 10000,
                "proxy-type": "SOCKS5", "proxy-host": "proxy.example", "proxy-port": 1080,
            })
        sock = socksocket.return_value
        sock.set_proxy.assert_called_once_with(socks.SOCKS5, "proxy.example", 1080, True, None, None)
        # the proxy connects to the server for us:
        sock.connect.assert_called_once_with(("server.example", 10000))


def main():
    unittest.main()


if __name__ == "__main__":
    main()
