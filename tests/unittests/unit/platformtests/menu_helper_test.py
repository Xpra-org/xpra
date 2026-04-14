#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import tempfile
import unittest
from unittest.mock import patch


class TestMenuHelperDefaults(unittest.TestCase):

    def test_load_menu_returns_dict(self):
        from xpra.platform.menu_helper import load_menu
        result = load_menu()
        assert isinstance(result, dict)

    def test_load_desktop_sessions_returns_dict(self):
        from xpra.platform.menu_helper import load_desktop_sessions
        result = load_desktop_sessions()
        assert isinstance(result, dict)

    def test_clear_cache_no_raise(self):
        from xpra.platform.menu_helper import clear_cache
        clear_cache()   # must not raise


class TestMenuHelperMain(unittest.TestCase):

    def _run_main(self, argv=None):
        saved = sys.argv
        sys.argv = argv or ["menu_helper"]
        try:
            from xpra.platform.menu_helper import main
            return main()
        finally:
            sys.argv = saved

    def test_main_no_args_returns_zero(self):
        result = self._run_main(["menu_helper"])
        assert result == 0

    def test_main_absolute_nonexistent_path(self):
        # argv[1] is an absolute path that does not exist:
        # load_icon_from_file is called; it may return None or raise,
        # but main() should still return 0.
        bogus = "/nonexistent/xpra/test/icon.png"
        result = self._run_main(["menu_helper", bogus])
        assert result == 0

    def test_main_relative_path_skipped(self):
        # a relative argument is not abs, so load_icon_from_file is never called
        result = self._run_main(["menu_helper", "relative_path"])
        assert result == 0

    def test_main_with_real_file(self):
        # Provide an absolute path to an existing (empty) file:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        try:
            result = self._run_main(["menu_helper", path])
            assert result == 0
        finally:
            os.unlink(path)

    def test_main_output_when_menu_empty(self):
        # Ensure main() runs to completion with an empty menu dict (default behaviour)
        with patch("builtins.print"):
            result = self._run_main(["menu_helper"])
        assert result == 0

    def test_main_output_when_menu_nonempty(self):
        fake_menu = {"App": {"Name": "App", "IconData": b"\x00" * 10}}
        with patch("xpra.platform.menu_helper.load_menu", return_value=fake_menu):
            with patch("builtins.print"):
                result = self._run_main(["menu_helper"])
        assert result == 0

    def test_main_output_when_sessions_nonempty(self):
        fake_sessions = {"XFCE": {"Name": "XFCE"}}
        with patch("xpra.platform.menu_helper.load_desktop_sessions", return_value=fake_sessions):
            with patch("builtins.print"):
                result = self._run_main(["menu_helper"])
        assert result == 0


def main():
    unittest.main()


if __name__ == "__main__":
    main()
