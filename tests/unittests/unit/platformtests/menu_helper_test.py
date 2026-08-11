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

PNG_DATA = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
SVG_DATA = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'


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


class TestMenuIconCache(unittest.TestCase):

    def test_cache_directory_selection(self):
        from xpra.platform.posix import menu_helper
        with tempfile.TemporaryDirectory() as cache_home, \
             patch.object(menu_helper.os, "geteuid", return_value=1000), \
             patch.dict(os.environ, {"XDG_CACHE_HOME": cache_home}):
            expected = os.path.join(cache_home, "xpra", "menu-icons")
            assert menu_helper.get_menu_icon_cache_dir() == expected
            assert menu_helper.get_menu_icon_cache_dirs() == (
                expected, menu_helper.GLOBAL_MENU_ICON_CACHE_DIR,
            )
        with patch.object(menu_helper.os, "geteuid", return_value=0):
            assert menu_helper.get_menu_icon_cache_dir() == menu_helper.GLOBAL_MENU_ICON_CACHE_DIR
        with patch.object(menu_helper.os, "geteuid", return_value=1000), \
             patch.dict(os.environ, {"XDG_CACHE_HOME": "relative-cache"}):
            assert menu_helper.get_menu_icon_cache_dir() == os.path.expanduser("~/.cache/xpra/menu-icons")

    def test_uncached_svg_is_not_exported(self):
        from xpra.platform.posix import menu_helper
        props = {"Name": "Test"}
        with patch.object(menu_helper, "do_find_icon", return_value="/icons/test.svg"), \
             patch.object(menu_helper.icon_util, "load_icon_from_file", return_value=(SVG_DATA, "svg")), \
             patch.object(menu_helper, "load_cached_svg", return_value=()):
            menu_helper.load_entry_icon(props)
        assert props["IconFile"] == "/icons/test.svg"
        assert "IconData" not in props
        assert "IconType" not in props

    def test_cached_svg_is_exported_as_png(self):
        from xpra.platform.posix import menu_helper
        props = {"Name": "Test"}
        with patch.object(menu_helper, "do_find_icon", return_value="/icons/test.svg"), \
             patch.object(menu_helper.icon_util, "load_icon_from_file", return_value=(SVG_DATA, "svg")), \
             patch.object(menu_helper, "load_cached_svg", return_value=(PNG_DATA, "png")):
            menu_helper.load_entry_icon(props)
        assert props["IconData"] == PNG_DATA
        assert props["IconType"] == "png"

    def test_cache_menu_icons_is_content_addressed(self):
        from xpra.platform.posix import menu_helper
        with tempfile.TemporaryDirectory() as tmpdir:
            svg_filename = os.path.join(tmpdir, "test.svg")
            with open(svg_filename, "wb") as f:
                f.write(SVG_DATA)
            cache_dir = os.path.join(tmpdir, "cache")
            applications = {"Utilities": {"IconFile": svg_filename, "Entries": {}}}
            sessions = {"Test": {"IconFile": svg_filename}}
            with patch.object(menu_helper, "get_menu_icon_cache_dir", return_value=cache_dir), \
                 patch.object(menu_helper, "load_menu", return_value=applications), \
                 patch.object(menu_helper, "load_desktop_sessions", return_value=sessions), \
                 patch.object(menu_helper.icon_util, "load_rsvg", return_value=True), \
                 patch.object(menu_helper.icon_util, "svg_to_png", return_value=PNG_DATA):
                assert menu_helper.cache_menu_icons() == 1
                assert menu_helper.cache_menu_icons() == 0
            cached_filename = menu_helper.cached_svg_filename(SVG_DATA, cache_dir)
            with open(cached_filename, "rb") as f:
                assert f.read() == PNG_DATA
            assert menu_helper.cached_svg_filename(SVG_DATA + b" ", cache_dir) != cached_filename
            with open(cached_filename, "wb") as f:
                f.write(b"invalid cache data")
            with patch.object(menu_helper, "get_menu_icon_cache_dir", return_value=cache_dir), \
                 patch.object(menu_helper, "load_menu", return_value=applications), \
                 patch.object(menu_helper, "load_desktop_sessions", return_value=sessions), \
                 patch.object(menu_helper.icon_util, "load_rsvg", return_value=True), \
                 patch.object(menu_helper.icon_util, "svg_to_png", return_value=PNG_DATA):
                assert menu_helper.cache_menu_icons() == 1


def main():
    unittest.main()


if __name__ == "__main__":
    main()
