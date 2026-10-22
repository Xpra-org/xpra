#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from xpra.config import paths


class ConfigPathsTest(unittest.TestCase):

    def test_file_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "index.html"
            file.write_text("html")
            self.assertEqual(paths.valid_html_path(directory, str(file) + ".missing", str(file)), str(file))
            self.assertEqual(paths.valid_html_path(directory), "")

    def test_supplied_installation_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "html5").mkdir()
            (root / "html5" / "connect.html").write_text("connect")
            (root / "doc").mkdir()
            (root / "doc" / "index.html").write_text("docs")
            with patch("xpra.platform.paths.get_resources_dir", return_value=directory), \
                 patch("xpra.platform.paths.get_app_dir", return_value=directory), patch.object(paths, "POSIX", False):
                self.assertEqual(paths.find_html5_path(), str(root / "html5" / "connect.html"))
                self.assertEqual(paths.find_docs_path(), str(root / "doc" / "index.html"))


if __name__ == "__main__":
    unittest.main()
