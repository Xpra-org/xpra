#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import MagicMock


class TestWebSocketHandler(unittest.TestCase):

    def _make_handler(self, headers=None, path="/", redirect_https=False):
        """Build a WebSocketRequestHandler with mocked I/O."""
        from xpra.net.websockets.handler import WebSocketRequestHandler

        handler = WebSocketRequestHandler.__new__(WebSocketRequestHandler)
        handler.headers = headers or {}
        handler.path = path
        handler.redirect_https = redirect_https
        handler.only_upgrade = False
        handler.close_connection = False
        handler.new_websocket_client = MagicMock()
        handler.connection = MagicMock()
        handler.wfile = MagicMock()
        handler.request = MagicMock()
        return handler

    # handle_websocket – header validation
    def test_handle_websocket_missing_version(self):
        handler = self._make_handler(headers={})
        with self.assertRaises(ValueError) as ctx:
            handler.handle_websocket()
        assert "Version" in str(ctx.exception)

    def test_handle_websocket_unsupported_version(self):
        handler = self._make_handler(headers={"Sec-WebSocket-Version": "99"})
        with self.assertRaises(ValueError) as ctx:
            handler.handle_websocket()
        assert "Unsupported" in str(ctx.exception) or "protocol" in str(ctx.exception).lower()

    def test_handle_websocket_missing_binary_protocol(self):
        handler = self._make_handler(headers={
            "Sec-WebSocket-Version": "13",
            "Sec-WebSocket-Protocol": "base64",
        })
        with self.assertRaises(ValueError) as ctx:
            handler.handle_websocket()
        assert "binary" in str(ctx.exception).lower()

    def test_handle_websocket_missing_key(self):
        handler = self._make_handler(headers={
            "Sec-WebSocket-Version": "13",
            "Sec-WebSocket-Protocol": "binary",
            "Sec-WebSocket-Key": "",
        })
        with self.assertRaises(ValueError) as ctx:
            handler.handle_websocket()
        assert "Key" in str(ctx.exception)

    def test_handle_websocket_valid(self):
        written = []
        handler = self._make_handler(headers={
            "Sec-WebSocket-Version": "13",
            "Sec-WebSocket-Protocol": "binary",
            "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
        })
        handler.write_byte_strings = lambda *bs: written.append(b"\r\n".join(bs))

        def fake_finish():
            pass
        handler.finish = fake_finish

        from unittest.mock import patch as mock_patch
        # super().finish() must not crash
        with mock_patch.object(type(handler).__mro__[2], "finish", lambda self: None, create=True):
            handler.handle_websocket()
        assert handler.new_websocket_client.called
        assert written

    # do_redirect_https
    def test_redirect_https_empty_host_header(self):
        # HTTPMessage returns None/empty for absent Host; simulate with empty string
        handler = self._make_handler(headers={"Host": ""}, redirect_https=True)
        errors = []
        handler.send_error = lambda code, msg="": errors.append((code, msg))
        handler.do_redirect_https()
        assert errors, "should have called send_error"
        assert errors[0][0] == 400

    def test_redirect_https_invalid_hostname(self):
        handler = self._make_handler(headers={"Host": "not a valid host!"}, redirect_https=True)
        errors = []
        handler.send_error = lambda code, msg="": errors.append((code, msg))
        handler.do_redirect_https()
        assert any(e[0] == 400 for e in errors)

    def test_redirect_https_valid_host_permanent(self):
        from xpra.net.websockets.handler import HTTPS_REDIRECT_PERMANENT
        written = []
        handler = self._make_handler(headers={"Host": "example.com"}, path="/index.html", redirect_https=True)
        handler.write_byte_strings = lambda *bs: written.extend(bs)
        handler.do_redirect_https()
        combined = b" ".join(written)
        assert b"https" in combined
        if HTTPS_REDIRECT_PERMANENT:
            assert b"301" in combined
        else:
            assert b"307" in combined

    def test_redirect_https_host_with_port(self):
        written = []
        handler = self._make_handler(headers={"Host": "example.com:8080"}, path="/", redirect_https=True)
        handler.write_byte_strings = lambda *bs: written.extend(bs)
        handler.do_redirect_https()
        combined = b" ".join(written)
        assert b"https" in combined
        assert b"example.com" in combined

    # write_byte_strings
    def test_write_byte_strings(self):
        handler = self._make_handler()
        written = []
        handler.wfile.write = lambda data: written.append(data)
        handler.wfile.flush = lambda: None
        handler.write_byte_strings(b"HTTP/1.1 200 OK", b"Content-Type: text/plain", b"", b"body")
        assert len(written) == 1
        assert b"\r\n" in written[0]
        assert b"HTTP/1.1 200 OK" in written[0]

    # module-level constants
    def test_constants(self):
        from xpra.net.websockets.handler import SUPPORT_HyBi_PROTOCOLS, WEBSOCKET_ONLY_UPGRADE
        assert "13" in SUPPORT_HyBi_PROTOCOLS
        assert "7" in SUPPORT_HyBi_PROTOCOLS
        assert "8" in SUPPORT_HyBi_PROTOCOLS
        assert isinstance(WEBSOCKET_ONLY_UPGRADE, bool)

    def test_server_version(self):
        from xpra.net.websockets.handler import WebSocketRequestHandler
        assert "WebSocket" in WebSocketRequestHandler.server_version


def main():
    unittest.main()


if __name__ == '__main__':
    main()
