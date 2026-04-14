#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest
from unittest.mock import MagicMock

try:
    import aioquic
    HAVE_AIOQUIC = bool(aioquic)
except ImportError:
    HAVE_AIOQUIC = False


def _make_handler(scope=None, www_dir="", scripts=None):
    from xpra.net.quic.http import HttpRequestHandler
    connection = MagicMock()
    protocol = MagicMock()
    server = MagicMock()
    server.get_http_scripts = lambda: scripts or {}
    server._www_dir = www_dir
    server._http_headers_dirs = []
    transmit = MagicMock()
    h = HttpRequestHandler(
        xpra_server=server,
        authority=b"localhost",
        connection=connection,
        protocol=protocol,
        scope=scope or {
            "http_version": "3",
            "method": "GET",
            "path": "/",
            "headers": {},
            "query_string": b"",
        },
        stream_id=4,
        transmit=transmit,
    )
    return h


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class TestSendResponseHeader(unittest.TestCase):

    def test_status_present(self):
        h = _make_handler()
        h.send_response_header(200, {"content-type": "text/plain"})
        header_dict = dict(h.connection.send_headers.call_args[1]["headers"])
        assert b":status" in header_dict
        assert header_dict[b":status"] == b"200"

    def test_server_and_date_included(self):
        h = _make_handler()
        h.send_response_header(404, {})
        headers = dict(h.connection.send_headers.call_args[1]["headers"])
        assert b"server" in headers
        assert b"date" in headers

    def test_custom_headers_merged(self):
        h = _make_handler()
        h.send_response_header(301, {"Location": "/new/path"})
        headers = dict(h.connection.send_headers.call_args[1]["headers"])
        assert b"Location" in headers
        assert headers[b"Location"] == b"/new/path"

    def test_stream_id_passed(self):
        h = _make_handler()
        h.send_response_header(200, {})
        kwargs = h.connection.send_headers.call_args[1]
        assert kwargs["stream_id"] == 4


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class TestSendResponseBody(unittest.TestCase):

    def test_body_passed_to_send_data(self):
        h = _make_handler()
        h.send_response_body(b"hello world")
        h.connection.send_data.assert_called_once()
        kwargs = h.connection.send_data.call_args[1]
        assert kwargs["data"] == b"hello world"
        assert kwargs["stream_id"] == 4
        assert kwargs["end_stream"] is True

    def test_more_body_sets_end_stream_false(self):
        h = _make_handler()
        h.send_response_body(b"chunk", more_body=True)
        kwargs = h.connection.send_data.call_args[1]
        assert kwargs["end_stream"] is False

    def test_empty_body(self):
        h = _make_handler()
        h.send_response_body()
        h.connection.send_data.assert_called_once()
        kwargs = h.connection.send_data.call_args[1]
        assert kwargs["data"] == b""


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class TestSendHttp3Response(unittest.TestCase):

    def test_calls_header_body_and_transmit(self):
        h = _make_handler()
        h.send_http3_response(200, {"x": "y"}, b"body")
        assert h.connection.send_headers.called
        assert h.connection.send_data.called
        assert h.transmit.called

    def test_no_body_skips_send_data(self):
        h = _make_handler()
        h.send_http3_response(204, {})
        assert h.connection.send_headers.called
        assert not h.connection.send_data.called
        assert h.transmit.called


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class TestHttpEventReceived(unittest.TestCase):

    def test_wrong_version_closes_protocol(self):
        scope = {
            "http_version": "2",
            "method": "GET",
            "path": "/",
            "headers": {},
            "query_string": b"",
        }
        h = _make_handler(scope=scope)
        h.http_event_received(MagicMock())
        assert h.protocol.close.called

    def test_post_not_supported_closes_protocol(self):
        scope = {
            "http_version": "3",
            "method": "POST",
            "path": "/upload",
            "headers": {},
            "query_string": b"",
        }
        h = _make_handler(scope=scope)
        h.http_event_received(MagicMock())
        assert h.protocol.close.called

    def test_script_handler_called(self):
        scope = {
            "http_version": "3",
            "method": "GET",
            "path": "/info",
            "headers": {},
            "query_string": b"",
        }
        script = MagicMock(return_value=(200, {}, b"script response"))
        h = _make_handler(scope=scope, scripts={"/info": script})
        h.http_event_received(MagicMock())
        assert script.called

    def test_get_with_missing_path_sends_404(self):
        scope = {
            "http_version": "3",
            "method": "GET",
            "path": "/nonexistent-xpra-test-file",
            "headers": {},
            "query_string": b"",
        }
        h = _make_handler(scope=scope, www_dir="/tmp")
        h.http_event_received(MagicMock())
        # should have sent response headers with 404
        headers = dict(h.connection.send_headers.call_args[1]["headers"])
        assert headers[b":status"] == b"404"


@unittest.skipUnless(HAVE_AIOQUIC, "aioquic not available")
class TestHandleGetRequest(unittest.TestCase):

    def test_missing_path_404(self):
        h = _make_handler(www_dir="/tmp")
        h.handle_get_request("/definitely-does-not-exist-xpra-unit-test")
        headers = dict(h.connection.send_headers.call_args[1]["headers"])
        assert headers[b":status"] == b"404"

    def test_existing_file_200(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"test content")
            path = f.name
        try:
            www_dir = os.path.dirname(path)
            fname = os.path.basename(path)
            h = _make_handler(www_dir=www_dir)
            h.handle_get_request("/" + fname)
            headers = dict(h.connection.send_headers.call_args[1]["headers"])
            assert headers[b":status"] == b"200"
        finally:
            os.unlink(path)

    def test_directory_without_index(self):
        with tempfile.TemporaryDirectory() as d:
            subdir = os.path.join(d, "subdir") + "/"
            os.makedirs(subdir)
            h = _make_handler(www_dir=d)
            # request the subdir with trailing slash (no index.html → 403 or listing)
            h.handle_get_request("/subdir/")
            headers = dict(h.connection.send_headers.call_args[1]["headers"])
            # expect 403 (directory listing disabled) or 200 (listing enabled)
            assert headers[b":status"] in (b"403", b"200")

    def test_directory_redirect(self):
        with tempfile.TemporaryDirectory() as d:
            subdir = os.path.join(d, "subdir")
            os.makedirs(subdir)
            h = _make_handler(www_dir=d)
            # request without trailing slash → 301 redirect
            h.handle_get_request("/subdir")
            headers = dict(h.connection.send_headers.call_args[1]["headers"])
            assert headers[b":status"] == b"301"


def main():
    unittest.main()


if __name__ == "__main__":
    main()
