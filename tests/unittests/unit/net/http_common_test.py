#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.net.http.common import http_response, http_status_request, json_response


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
