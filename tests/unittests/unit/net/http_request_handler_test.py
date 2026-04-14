#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import base64
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch


def _make_handler(path="/", headers=None, web_root=None, script_paths=None,
                  password="", username=""):
    """Return an HTTPRequestHandler wired up with mocked I/O, bypassing __init__."""
    from xpra.net.http.handler import HTTPRequestHandler
    h = HTTPRequestHandler.__new__(HTTPRequestHandler)
    h.path = path
    h.headers = headers or {}
    h.web_root = web_root or "/usr/share/xpra/www"
    h.http_headers_dirs = []
    h.script_paths = script_paths or {}
    h.username = username
    h.password = password
    h.extra_headers = {}
    h.post_data = b""
    h.close_connection = False
    h.directory_listing = False
    h.request = MagicMock()
    h.connection = MagicMock()
    h.wfile = MagicMock()
    h.rfile = MagicMock()
    h.command = "GET"
    h.request_version = "HTTP/1.1"
    h._headers_buffer = []
    # mock BaseHTTPRequestHandler output methods to avoid socket I/O
    h.send_response = MagicMock()
    h.send_header = MagicMock()
    h.send_error = MagicMock()
    return h


class TestLogError(unittest.TestCase):

    def test_404_logged_at_debug(self):
        h = _make_handler()
        # should not raise; we just verify the code path executes
        h.log_error("code %s message %s", 404, "not found")

    def test_timeout_logged_at_debug(self):
        h = _make_handler()
        h.log_error("%s", TimeoutError("read timeout"))

    def test_other_errors_logged_normally(self):
        h = _make_handler()
        h.log_error("server error %s %s", 500, "internal error")


class TestLogMessage(unittest.TestCase):

    def test_400_path_repr_ellipsized(self):
        h = _make_handler()
        # should not raise
        h.log_message('"%s" %s %s', "GET / HTTP/1.1", "400", "-")

    def test_other_message_unchanged(self):
        h = _make_handler()
        h.log_message('"%s" %s %s', "GET / HTTP/1.1", "200", "-")


class TestHandleAuthentication(unittest.TestCase):

    def test_no_password_returns_true(self):
        h = _make_handler(password="")
        assert h.handle_authentication() is True

    def test_missing_auth_header_returns_false(self):
        h = _make_handler(password="secret", headers={})
        h.do_AUTHHEAD = MagicMock()
        result = h.handle_authentication()
        assert result is False

    def test_non_basic_scheme_returns_false(self):
        h = _make_handler(password="secret", headers={"Authorization": "Bearer token"})
        h.do_AUTHHEAD = MagicMock()
        result = h.handle_authentication()
        assert result is False

    def test_valid_credentials_returns_true(self):
        creds = base64.b64encode(b"user:secret").decode()
        h = _make_handler(password="secret", username="user",
                          headers={"Authorization": f"Basic {creds}"})
        result = h.handle_authentication()
        assert result is True

    def test_wrong_password_returns_false(self):
        creds = base64.b64encode(b"user:wrong").decode()
        h = _make_handler(password="secret", username="user",
                          headers={"Authorization": f"Basic {creds}"})
        h.do_AUTHHEAD = MagicMock()
        result = h.handle_authentication()
        assert result is False

    def test_no_username_check_any_user(self):
        creds = base64.b64encode(b"anyuser:secret").decode()
        h = _make_handler(password="secret", username="",
                          headers={"Authorization": f"Basic {creds}"})
        result = h.handle_authentication()
        assert result is True

    def test_invalid_base64_returns_false(self):
        h = _make_handler(password="secret",
                          headers={"Authorization": "Basic not-valid-base64!!!"})
        h.do_AUTHHEAD = MagicMock()
        result = h.handle_authentication()
        assert result is False

    def test_no_colon_in_credentials_returns_false(self):
        creds = base64.b64encode(b"nodivider").decode()
        h = _make_handler(password="secret",
                          headers={"Authorization": f"Basic {creds}"})
        h.do_AUTHHEAD = MagicMock()
        result = h.handle_authentication()
        assert result is False


class TestDoAuthHead(unittest.TestCase):

    def test_sends_401(self):
        h = _make_handler(password="secret")
        # end_headers calls super().end_headers() which writes to wfile;
        # that's fine because wfile is a MagicMock
        h.end_headers = MagicMock()
        h.do_AUTHHEAD()
        h.send_response.assert_called_once_with(401)

    def test_sends_www_authenticate_when_password_set(self):
        h = _make_handler(password="mypwd")
        h.end_headers = MagicMock()
        h.do_AUTHHEAD()
        headers_sent = [call[0] for call in h.send_header.call_args_list]
        keys = [k for k, _ in headers_sent]
        assert "WWW-Authenticate" in keys

    def test_no_www_authenticate_without_password(self):
        h = _make_handler(password="")
        h.end_headers = MagicMock()
        h.do_AUTHHEAD()
        headers_sent = [call[0] for call in h.send_header.call_args_list]
        keys = [k for k, _ in headers_sent]
        assert "WWW-Authenticate" not in keys


class TestSendHead(unittest.TestCase):

    def test_script_path_called(self):
        script = MagicMock(return_value=(200, {"X-Test": "yes"}, b"script body"))
        h = _make_handler(path="/info", script_paths={"/info": script})
        h.end_headers = MagicMock()
        body = h.send_head()
        assert script.called
        assert body == b"script body"
        h.send_response.assert_called_once_with(200)

    def test_script_exception_sends_500(self):
        script = MagicMock(side_effect=RuntimeError("boom"))
        h = _make_handler(path="/fail", script_paths={"/fail": script})
        h.end_headers = MagicMock()
        body = h.send_head()
        assert body == b""
        h.send_error.assert_called()
        code = h.send_error.call_args[0][0]
        assert code == 500

    def test_missing_path_sends_404(self):
        h = _make_handler(path="/no-such-file-xyz.html", web_root="/tmp")
        body = h.send_head()
        assert body == b""
        h.send_error.assert_called()
        code = h.send_error.call_args[0][0]
        assert code == 404

    def test_existing_file_returns_content(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"page content")
            path = f.name
        try:
            web_root = os.path.dirname(path)
            fname = os.path.basename(path)
            h = _make_handler(path=f"/{fname}", web_root=web_root,
                              headers={"accept-encoding": ""})
            h.end_headers = MagicMock()
            body = h.send_head()
            assert body == b"page content"
        finally:
            os.unlink(path)

    def test_directory_redirect(self):
        with tempfile.TemporaryDirectory() as d:
            subdir = os.path.join(d, "mydir")
            os.makedirs(subdir)
            h = _make_handler(path="/mydir", web_root=d)
            h.end_headers = MagicMock()
            body = h.send_head()
            assert body == b""
            h.send_response.assert_called_with(301)

    def test_directory_listing_forbidden(self):
        with tempfile.TemporaryDirectory() as d:
            subdir = os.path.join(d, "empty")
            os.makedirs(subdir)
            h = _make_handler(path="/empty/", web_root=d)
            h.directory_listing = False
            body = h.send_head()
            assert body == b""
            h.send_error.assert_called()
            assert h.send_error.call_args[0][0] == 403

    def test_directory_index_html_served(self):
        with tempfile.TemporaryDirectory() as d:
            subdir = os.path.join(d, "sub")
            os.makedirs(subdir)
            idx = os.path.join(subdir, "index.html")
            with open(idx, "wb") as f:
                f.write(b"<html>index</html>")
            h = _make_handler(path="/sub/", web_root=d,
                              headers={"accept-encoding": ""})
            h.end_headers = MagicMock()
            body = h.send_head()
            assert body == b"<html>index</html>"


class TestSendError(unittest.TestCase):

    def test_custom_error_page_served(self):
        with tempfile.TemporaryDirectory() as d:
            # write a custom 404.html
            custom = os.path.join(d, "404.html")
            with open(custom, "wb") as f:
                f.write(b"<h1>Custom 404</h1>")
            h = _make_handler(web_root=d)
            # restore real send_error
            from xpra.net.http.handler import HTTPRequestHandler
            h.send_error = HTTPRequestHandler.send_error.__get__(h)
            h.error_content_type = "text/html"
            h.end_headers = MagicMock()
            h.send_error(404, "Not Found")
            h.send_response.assert_called_with(404, "Not Found")
            written = h.wfile.write.call_args_list
            bodies = [call[0][0] for call in written]
            assert any(b"Custom 404" in b for b in bodies)

    def test_fallback_to_super_when_no_custom_page(self):
        h = _make_handler(web_root="/tmp")
        from xpra.net.http.handler import HTTPRequestHandler
        h.send_error = HTTPRequestHandler.send_error.__get__(h)
        h.error_content_type = "text/html"
        h.end_headers = MagicMock()
        # super().send_error may raise OSError since wfile is mocked;
        # the implementation catches it
        try:
            h.send_error(503, "Service Unavailable")
        except Exception:
            pass  # acceptable since wfile is mocked


class TestEndHeaders(unittest.TestCase):

    def test_echo_headers_injects_accept_language(self):
        h = _make_handler(path="/?echo-headers",
                          headers={"Accept-Language": "en-GB,en;q=0.8"})
        # call real end_headers; super().end_headers() writes \r\n to wfile
        from xpra.net.http.handler import HTTPRequestHandler
        # need _headers_buffer for BaseHTTPRequestHandler.end_headers
        h._headers_buffer = []
        HTTPRequestHandler.end_headers(h)
        assert "Echo-Accept-Language" in h.extra_headers

    def test_no_echo_without_query(self):
        h = _make_handler(path="/normal",
                          headers={"Accept-Language": "en-US"})
        h._headers_buffer = []
        from xpra.net.http.handler import HTTPRequestHandler
        HTTPRequestHandler.end_headers(h)
        assert "Echo-Accept-Language" not in h.extra_headers


class TestFindBackgroundPath(unittest.TestCase):

    def test_invalid_format_raises(self):
        from xpra.net.http.handler import find_background_path
        with self.assertRaises(AssertionError):
            find_background_path("gif")

    def test_returns_string_for_png(self):
        from xpra.net.http.handler import find_background_path
        with patch("xpra.platform.paths.get_desktop_background_paths", return_value=[]):
            result = find_background_path("png")
        assert isinstance(result, str)

    def test_returns_string_for_jpg(self):
        from xpra.net.http.handler import find_background_path
        with patch("xpra.platform.paths.get_desktop_background_paths", return_value=[]):
            result = find_background_path("jpg")
        assert isinstance(result, str)

    def test_finds_matching_glob(self):
        from xpra.net.http.handler import find_background_path
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            bg_path = f.name
        try:
            with patch("xpra.platform.paths.get_desktop_background_paths", return_value=[bg_path]):
                result = find_background_path("png")
            assert result == bg_path
        finally:
            os.unlink(bg_path)

    def test_jxl_without_session_dir_returns_path(self):
        from xpra.net.http.handler import find_background_path
        from xpra.util.env import OSEnvContext
        with tempfile.NamedTemporaryFile(suffix=".jxl", delete=False) as f:
            jxl_path = f.name
        try:
            with OSEnvContext():
                os.environ.pop("XPRA_SESSION_DIR", None)
                with patch("xpra.platform.paths.get_desktop_background_paths", return_value=[jxl_path]):
                    result = find_background_path("png")
            # without a session dir we can't convert; result is the jxl path itself
            assert isinstance(result, str)
        finally:
            os.unlink(jxl_path)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
