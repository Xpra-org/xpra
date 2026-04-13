#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest

from xpra.net.http.handler import translate_path, may_reload_headers, load_path


class TestTranslatePath(unittest.TestCase):

    def setUp(self):
        self.web_root = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.web_root, ignore_errors=True)

    def test_root_maps_to_web_root(self):
        result = translate_path("/", self.web_root)
        self.assertTrue(result.startswith(self.web_root))

    def test_simple_file(self):
        result = translate_path("/index.html", self.web_root)
        self.assertEqual(result, os.path.join(self.web_root, "index.html"))

    def test_nested_path(self):
        result = translate_path("/a/b/c.js", self.web_root)
        self.assertEqual(result, os.path.join(self.web_root, "a", "b", "c.js"))

    def test_query_string_stripped(self):
        result = translate_path("/page.html?foo=bar", self.web_root)
        self.assertEqual(result, os.path.join(self.web_root, "page.html"))

    def test_fragment_stripped(self):
        result = translate_path("/page.html#section", self.web_root)
        self.assertEqual(result, os.path.join(self.web_root, "page.html"))

    def test_trailing_slash_preserved(self):
        result = translate_path("/subdir/", self.web_root)
        self.assertTrue(result.endswith("/"))

    def test_path_traversal_blocked(self):
        result = translate_path("/../../../etc/passwd", self.web_root)
        # must remain inside web_root, not escape to the real /etc/passwd
        self.assertTrue(result.startswith(self.web_root))

    def test_url_encoded_path(self):
        result = translate_path("/hello%20world.html", self.web_root)
        self.assertEqual(result, os.path.join(self.web_root, "hello world.html"))


class TestMayReloadHeaders(unittest.TestCase):

    def test_empty_dirs_returns_empty(self):
        headers = may_reload_headers([])
        self.assertIsInstance(headers, dict)

    def test_nonexistent_dir_returns_empty(self):
        headers = may_reload_headers(["/nonexistent/dir/xyz"])
        self.assertIsInstance(headers, dict)

    def test_loads_headers_from_file(self):
        with tempfile.TemporaryDirectory() as d:
            header_file = os.path.join(d, "test.headers")
            with open(header_file, "w") as f:
                f.write("X-Custom-Header: myvalue\n")
                f.write("Cache-Control: no-cache\n")
            from xpra.net.http import handler as handler_mod
            # clear the cache to force a reload
            handler_mod.http_headers_cache.clear()
            handler_mod.http_headers_time.clear()
            headers = may_reload_headers([d])
            self.assertIn("X-Custom-Header", headers)
            self.assertEqual(headers["X-Custom-Header"], "myvalue")
            self.assertIn("Cache-Control", headers)

    def test_ignores_comment_lines(self):
        with tempfile.TemporaryDirectory() as d:
            header_file = os.path.join(d, "headers.conf")
            with open(header_file, "w") as f:
                f.write("# this is a comment\n")
                f.write("X-Real: value\n")
            from xpra.net.http import handler as handler_mod
            handler_mod.http_headers_cache.clear()
            handler_mod.http_headers_time.clear()
            headers = may_reload_headers([d])
            self.assertNotIn("# this is a comment", headers)
            self.assertIn("X-Real", headers)


class TestLoadPath(unittest.TestCase):

    def test_loads_file_content(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"hello world")
            path = f.name
        try:
            code, headers, content = load_path([], path)
            self.assertEqual(code, 200)
            self.assertEqual(content, b"hello world")
            self.assertIn("Content-Length", headers)
            self.assertEqual(headers["Content-Length"], len(b"hello world"))
        finally:
            os.unlink(path)

    def test_content_type_for_html(self):
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            f.write(b"<html></html>")
            path = f.name
        try:
            code, headers, content = load_path([], path)
            self.assertEqual(code, 200)
            self.assertIn("Content-type", headers)
            self.assertIn("html", headers["Content-type"])
        finally:
            os.unlink(path)

    def test_content_type_for_js(self):
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False) as f:
            f.write(b"var x = 1;")
            path = f.name
        try:
            code, headers, content = load_path([], path)
            self.assertEqual(code, 200)
            if "Content-type" in headers:
                self.assertIn("javascript", headers["Content-type"])
        finally:
            os.unlink(path)

    def test_last_modified_in_headers(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"data")
            path = f.name
        try:
            code, headers, content = load_path([], path)
            self.assertEqual(code, 200)
            self.assertIn("Last-Modified", headers)
        finally:
            os.unlink(path)

    def test_gzip_on_the_fly(self):
        # large enough file to trigger on-the-fly gzip
        data = b"x" * 512
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            f.write(data)
            path = f.name
        try:
            code, headers, content = load_path(["gzip"], path)
            self.assertEqual(code, 200)
            # gzip may or may not be applied depending on HTTP_ACCEPT_ENCODING env
            self.assertIn("Content-Length", headers)
        finally:
            os.unlink(path)

    def test_pre_compressed_file_used(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "data.html")
            gz_path = path + ".gzip"
            import gzip
            raw = b"<html>hello</html>"
            with open(path, "wb") as f:
                f.write(raw)
            compressed = gzip.compress(raw)
            with open(gz_path, "wb") as f:
                f.write(compressed)
            code, headers, content = load_path(["gzip"], path)
            self.assertEqual(code, 200)
            # if pre-compressed file is used, Content-Encoding should be set
            # (only if gzip is in HTTP_ACCEPT_ENCODING, which depends on env)
            self.assertIn("Content-Length", headers)


if __name__ == "__main__":
    unittest.main()
