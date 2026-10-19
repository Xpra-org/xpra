#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from xpra.net.socket_util import SocketListener
from xpra.server import network_util
from xpra.server.network_util import can_upgrade, get_ssl_socket_options, get_socket_info, find_www_dir


class TestNetworkUtil(unittest.TestCase):

    def test_can_upgrade_flags(self):
        with patch("xpra.server.network_util.has_websocket_handler", return_value=True):
            assert not can_upgrade("tcp", "ssl", {})
            assert can_upgrade("tcp", "ssl", {}, ssl=True)
            assert can_upgrade("tcp", "wss", {}, ssl=True, websocket=True)
            assert not can_upgrade("tcp", "wss", {}, ssl=True)
            assert can_upgrade("ws", "wss", {}, ssl=True)
            assert can_upgrade("ssl", "wss", {}, websocket=True)
            assert can_upgrade("tcp", "ssh", {}, ssh=True)
            assert can_upgrade("tcp", "rfb", {}, rfb=True)
            assert can_upgrade("tcp", "rdp", {}, rdp=True)
            assert not can_upgrade("udp", "ssl", {}, ssl=True)

    def test_can_upgrade_socket_options_win(self):
        with patch("xpra.server.network_util.has_websocket_handler", return_value=True):
            assert can_upgrade("tcp", "ssl", {"ssl": "yes"})
            assert not can_upgrade("tcp", "ssl", {"ssl": "no"}, ssl=True)
            assert not can_upgrade("tcp", "ssh", {"ssh": "off"}, ssh=True)

    def test_can_upgrade_without_websocket_handler(self):
        with patch("xpra.server.network_util.has_websocket_handler", return_value=False):
            assert not can_upgrade("tcp", "ws", {"ws": "yes"}, websocket=True)

    def test_ssl_socket_options(self):
        attrs = {"cert": "/a.pem", "client-verify-mode": "none"}
        options = {"ssl-cert": "/b.pem", "ssl-key-password": "x", "auth": "none"}
        assert get_ssl_socket_options(attrs, options) == {
            "cert": "/b.pem",
            "client_verify_mode": "none",
            "key_password": "x",
        }
        # the attributes are not modified:
        assert attrs["cert"] == "/a.pem"

    def test_socket_info(self):
        sockets = [
            SocketListener("tcp", object(), ("127.0.0.1", 10000), {}, lambda: None, lambda: None),
            SocketListener("socket", object(), "/run/xpra/test", {}, lambda: None, lambda: None),
        ]
        with patch("xpra.net.net_util.import_netifaces", return_value=None):
            si = get_socket_info(sockets, websocket=True, ssl=True)
        assert si["tcp"] == {"listeners": [("127.0.0.1", 10000)], "addresses": [("127.0.0.1", 10000)]}
        assert si["ws"]["addresses"] == [("127.0.0.1", 10000)]
        assert si["wss"]["addresses"] == [("127.0.0.1", 10000)]
        assert si["ssl"]["addresses"] == [("127.0.0.1", 10000)]
        assert "ssh" not in si
        assert si["socket"] == {"listeners": ["/run/xpra/test"]}

    def test_find_www_dir_disabled(self):
        assert find_www_dir(False, "/somewhere") == (False, "", [])

    def test_find_www_dir_missing(self):
        with patch.object(network_util, "httplog"):
            html, www_dir, headers = find_www_dir(True, "/this/path/does/not/exist")
        assert html is False
        assert headers == []
        assert www_dir

    def test_parse_html_option_needs_socket(self):
        opts = SimpleNamespace(html="on", bind=(), bind_tcp=(), bind_ws=(), bind_wss=(), bind_ssl=())
        with patch.object(network_util, "httplog"):
            assert network_util.parse_html_option(opts) == (False, "")


def main():
    unittest.main()


if __name__ == "__main__":
    main()
