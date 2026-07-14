#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.net.http.common import http_response, http_status_request, json_response, check_origin, parse_origin


class TestHttpOrigin(unittest.TestCase):

    def test_parse_origin(self):
        assert parse_origin("https://desktop.example") == ("https", "desktop.example", 443)
        assert parse_origin("HTTP://Desktop.Example:80") == ("http", "desktop.example", 80)
        assert parse_origin("wss://desktop.example") == ("https", "desktop.example", 443)
        assert parse_origin("ws://localhost:14500") == ("http", "localhost", 14500)
        # anything we cannot parse:
        for invalid in ("null", "", "desktop.example", "http://localhost:port"):
            assert parse_origin(invalid) == ("", "", 0), f"{invalid!r} should not parse"

    def test_no_origin_header_is_allowed(self):
        # native xpra clients don't send an `Origin` header,
        # and browsers cannot be made to omit it:
        for policy in ("auto", "any", "none", "https://desktop.example"):
            assert check_origin("", "localhost:14500", policy)

    def test_auto_same_origin(self):
        assert check_origin("http://localhost:14500", "localhost:14500", "auto")
        assert check_origin("https://localhost:14500", "localhost:14500", "auto")
        assert check_origin("http://desktop.example", "desktop.example", "auto")
        # behind a TLS terminating proxy, the scheme we see does not match the browser's:
        assert check_origin("https://desktop.example", "desktop.example", "auto")

    def test_auto_cross_origin(self):
        assert not check_origin("http://evil.example", "localhost:14500", "auto")
        # another port on the same host is another origin:
        assert not check_origin("http://localhost:8080", "localhost:14500", "auto")
        # sandboxed iframes and `file://` pages:
        assert not check_origin("null", "localhost:14500", "auto")
        # fail closed without a `Host` header:
        assert not check_origin("http://localhost:14500", "", "auto")

    def test_any(self):
        for policy in ("any", "all", "*"):
            assert check_origin("http://evil.example", "localhost:14500", policy)
            assert check_origin("null", "localhost:14500", policy)

    def test_strict_rejects_missing_origin(self):
        for policy in ("strict", "strict,https://desktop.example", "any,strict"):
            assert not check_origin("", "localhost:14500", policy)

    def test_strict_alone_is_same_origin(self):
        assert check_origin("http://localhost:14500", "localhost:14500", "strict")
        assert not check_origin("http://evil.example", "localhost:14500", "strict")

    def test_strict_with_allowlist(self):
        policy = "strict,https://desktop.example"
        assert check_origin("https://desktop.example", "localhost:14500", policy)
        assert not check_origin("http://evil.example", "localhost:14500", policy)
        assert not check_origin("", "localhost:14500", policy)

    def test_none(self):
        # every request carrying an `Origin` header is rejected:
        for policy in ("none", "no", "off"):
            assert not check_origin("http://localhost:14500", "localhost:14500", policy)

    def test_allowlist(self):
        policy = "https://desktop.example, http://localhost:8080"
        assert check_origin("https://desktop.example", "localhost:14500", policy)
        assert check_origin("https://desktop.example:443", "localhost:14500", policy)
        assert check_origin("http://localhost:8080", "localhost:14500", policy)
        assert not check_origin("http://desktop.example", "localhost:14500", policy)
        assert not check_origin("https://evil.example", "localhost:14500", policy)
        # an unparsable origin must not match an unparsable allowlist entry:
        assert not check_origin("null", "localhost:14500", "null,https://desktop.example")


class TestHttpCommon(unittest.TestCase):

    def test_empty_response(self):
        code, headers, body = http_response(b"")
        assert code == 404
        assert body == b""

    def test_bytes_response(self):
        code, headers, body = http_response(b"hello")
        assert code == 200
        assert body == b"hello"
        assert headers["Content-Length"] == 5

    def test_string_response(self):
        code, headers, body = http_response("hello")
        assert code == 200
        assert body == b"hello"

    def test_status_request(self):
        code, _headers, body = http_status_request("/", b"")
        assert code == 200
        assert b"ready" in body

    def test_json_response(self):
        code, headers, body = json_response({"key": "value"})
        assert code == 200
        assert b"key" in body
        assert "application/json" in headers["Content-type"]


def main():
    unittest.main()


if __name__ == '__main__':
    main()
