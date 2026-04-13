#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import tempfile
import unittest

from xpra.net.http.directory_listing import list_directory


class TestListDirectory(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_nonexistent_path(self):
        code, headers, body = list_directory("/nonexistent/path/xyz")
        self.assertEqual(code, 404)
        self.assertIsInstance(body, bytes)

    def test_empty_directory(self):
        code, headers, body = list_directory(self.tmpdir)
        self.assertEqual(code, 200)
        self.assertIn("Content-type", headers)
        self.assertIn("Content-Length", headers)
        self.assertIn(b"Directory listing", body)

    def test_directory_with_files(self):
        open(os.path.join(self.tmpdir, "file.txt"), "w").close()
        open(os.path.join(self.tmpdir, "readme.md"), "w").close()
        code, headers, body = list_directory(self.tmpdir)
        self.assertEqual(code, 200)
        self.assertIn(b"file.txt", body)
        self.assertIn(b"readme.md", body)

    def test_subdirectory_marked_with_slash(self):
        subdir = os.path.join(self.tmpdir, "subdir")
        os.mkdir(subdir)
        code, headers, body = list_directory(self.tmpdir)
        self.assertEqual(code, 200)
        self.assertIn(b"subdir/", body)

    @unittest.skipIf(sys.platform == "win32", "symlinks may require elevation on Windows")
    def test_symlink_marked_with_at(self):
        target = os.path.join(self.tmpdir, "target.txt")
        open(target, "w").close()
        link = os.path.join(self.tmpdir, "link")
        os.symlink(target, link)
        code, headers, body = list_directory(self.tmpdir)
        self.assertEqual(code, 200)
        self.assertIn(b"link@", body)

    def test_html_escaping(self):
        # File name with characters that need HTML escaping
        name = "a&b.txt"
        open(os.path.join(self.tmpdir, name), "w").close()
        code, headers, body = list_directory(self.tmpdir)
        self.assertEqual(code, 200)
        self.assertIn(b"a&amp;b.txt", body)

    def test_content_length_matches_body(self):
        open(os.path.join(self.tmpdir, "x.txt"), "w").close()
        code, headers, body = list_directory(self.tmpdir)
        self.assertEqual(code, 200)
        self.assertEqual(int(headers["Content-Length"]), len(body))

    def test_returns_valid_html(self):
        code, headers, body = list_directory(self.tmpdir)
        self.assertEqual(code, 200)
        self.assertIn(b"<!DOCTYPE", body)
        self.assertIn(b"</html>", body)


if __name__ == "__main__":
    unittest.main()
