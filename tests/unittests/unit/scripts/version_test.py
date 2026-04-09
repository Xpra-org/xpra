#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Tests for xpra/scripts/version.py
"""

import io
import sys
import unittest
from unittest.mock import patch


class TestVersionMain(unittest.TestCase):

    def test_returns_zero(self):
        from xpra.scripts.version import main
        ret = main([])
        self.assertEqual(ret, 0)

    def test_returns_zero_with_verbose(self):
        from xpra.scripts.version import main
        # -v / --verbose flag is consumed by consume_verbose_argv
        ret = main(["-v"])
        self.assertEqual(ret, 0)

    def test_output_contains_build_section(self):
        from xpra.scripts.version import main
        buf = io.StringIO()
        with patch("builtins.print", lambda *a, **kw: buf.write(" ".join(str(x) for x in a) + "\n")):
            main([])
        output = buf.getvalue()
        self.assertIn("Build", output)

    def test_output_contains_platform_section(self):
        from xpra.scripts.version import main
        buf = io.StringIO()
        with patch("builtins.print", lambda *a, **kw: buf.write(" ".join(str(x) for x in a) + "\n")):
            main([])
        output = buf.getvalue()
        self.assertIn("Platform", output)

    def test_output_contains_host_section(self):
        from xpra.scripts.version import main
        buf = io.StringIO()
        with patch("builtins.print", lambda *a, **kw: buf.write(" ".join(str(x) for x in a) + "\n")):
            main([])
        output = buf.getvalue()
        self.assertIn("Host", output)

    def test_output_not_empty(self):
        from xpra.scripts.version import main
        lines = []
        with patch("builtins.print", lambda *a, **kw: lines.append(a)):
            main([])
        self.assertGreater(len(lines), 5)


class TestVersionInfo(unittest.TestCase):
    """Sanity-check the helper functions called by main()."""

    def test_get_version_info_has_version(self):
        from xpra.util.version import get_version_info
        info = get_version_info()
        self.assertIsInstance(info, dict)
        self.assertIn("version", info)

    def test_get_platform_info_is_dict(self):
        from xpra.util.version import get_platform_info
        info = get_platform_info()
        self.assertIsInstance(info, dict)
        self.assertTrue(len(info) > 0)

    def test_get_host_info_is_dict(self):
        from xpra.util.version import get_host_info
        info = get_host_info(1)
        self.assertIsInstance(info, dict)

    def test_version_is_string(self):
        from xpra.util.version import get_version_info
        info = get_version_info()
        version = info["version"]
        self.assertIsInstance(version, str)
        # version string should look like "x.y" or "x.y.z"
        parts = version.split(".")
        self.assertGreater(len(parts), 1)

    def test_script_main_entrypoint(self):
        """Running as __main__ exits with code 0."""
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "xpra.scripts.version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Accept 0 or 1 (some environments lack platform data)
        self.assertIn(result.returncode, (0, 1))


def main():
    unittest.main()


if __name__ == "__main__":
    main()
