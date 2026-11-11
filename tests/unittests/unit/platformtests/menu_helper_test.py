#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

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


class TestPyxdgAPI(unittest.TestCase):

    def setUp(self):
        from xpra.platform.posix import menu_helper
        self.menu_helper = menu_helper

    def test_clear_cache_uses_pyxdg(self):
        calls = []
        fake = SimpleNamespace(clear_cache=lambda: calls.append(True), themes=["unchanged"])
        with patch.object(self.menu_helper, "IconTheme", fake):
            self.menu_helper.clear_cache()
        assert calls == [True]
        assert fake.themes == ["unchanged"]

    def test_clear_cache_older_pyxdg(self):
        fake = SimpleNamespace(themes=["theme"], theme_cache={1: 1}, dir_cache={1: 1}, icon_cache={1: 1})
        with patch.object(self.menu_helper, "IconTheme", fake):
            self.menu_helper.clear_cache()
        assert (fake.themes, fake.theme_cache, fake.dir_cache, fake.icon_cache) == ([], {}, {}, {})

    def test_init_themes_get_themes(self):
        init_themes = getattr(self.menu_helper, "init_themes", None)
        if not init_themes:
            self.skipTest("pyxdg is not installed")
        theme = SimpleNamespace(name="test-theme")
        for fake in (
            SimpleNamespace(get_themes=lambda _name: [theme]),
            SimpleNamespace(__get_themes=lambda _name: [theme]),
        ):
            with patch.object(self.menu_helper, "IconTheme", fake), \
                 patch.object(self.menu_helper, "Config", SimpleNamespace(icon_theme="test-theme")), \
                 patch.object(self.menu_helper, "themes", {}), \
                 patch.object(self.menu_helper.glob, "glob", return_value=[]):
                init_themes()
                assert self.menu_helper.themes == {"test-theme": theme}, fake


def raise_from_pyxdg_menu(exc: BaseException) -> BaseException:
    """ raises `exc` from code which looks like it comes from pyxdg's `xdg/Menu.py` """
    code = compile("raise exc", os.path.join("/usr", "lib", "xdg", "Menu.py"), "exec")
    try:
        exec(code, {"exc": exc})
    except BaseException as e:
        return e
    raise AssertionError("not raised")


class TestPyxdgAstError(unittest.TestCase):

    def setUp(self):
        from xpra.platform.posix import menu_helper
        self.menu_helper = menu_helper

    def check(self, exc: BaseException, version: str) -> bool:
        with patch.object(self.menu_helper, "get_pyxdg_version", return_value=version):
            return self.menu_helper.is_pyxdg_ast_error(exc)

    def test_detection(self):
        lineno = TypeError("ast.Expression.__init__ got an unexpected keyword argument 'lineno'")
        ast_str = AttributeError("module 'ast' has no attribute 'Str'")
        for exc in (lineno, ast_str):
            assert self.check(raise_from_pyxdg_menu(exc), "0.28")
            assert self.check(raise_from_pyxdg_menu(exc), "")
            assert not self.check(raise_from_pyxdg_menu(exc), "0.29")
            assert not self.check(raise_from_pyxdg_menu(exc), "1.0")
        # not raised from pyxdg's Menu.py:
        try:
            raise TypeError("ast.Expression.__init__ got an unexpected keyword argument 'lineno'")
        except TypeError as e:
            assert not self.check(e, "0.28")
        # not an ast error:
        assert not self.check(raise_from_pyxdg_menu(TypeError("something else")), "0.28")
        assert not self.check(raise_from_pyxdg_menu(ValueError("ast")), "0.28")

    def test_menu_loading_stops(self):
        try:
            from xdg import Menu
        except ImportError:
            self.skipTest("pyxdg is not installed")
        calls = []

        def parse(*_args):
            calls.append(True)
            raise raise_from_pyxdg_menu(TypeError("ast.Expression.__init__ got an unexpected keyword argument 'lineno'"))

        log = Mock()
        with patch.object(Menu, "parse", parse), \
             patch("xpra.seccomp.menu.is_enabled", return_value=False), \
             patch.object(self.menu_helper, "get_pyxdg_version", return_value="0.28"), \
             patch.object(self.menu_helper, "first_time", return_value=True), \
             patch.object(self.menu_helper, "log", log), \
             patch.dict(os.environ, {"XDG_CONFIG_DIRS": "/etc/xdg"}):
            assert self.menu_helper.do_load_xdg_menu_data() == {}
        assert calls == [True], "should not retry"
        errors = [call.args[0] for call in log.error.call_args_list]
        assert any("pyxdg 0.28 is not compatible with Python" in msg for msg in errors), errors
        assert any(self.menu_helper.PYXDG_URL in msg for msg in errors), errors


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

    def test_cache_menu_icons_read_only(self):
        from xpra.platform.posix import menu_helper
        if os.geteuid() == 0:
            self.skipTest("root can write to read-only directories")
        with tempfile.TemporaryDirectory() as home:
            os.chmod(home, 0o500)
            try:
                for cache_dir in (os.path.join(home, ".cache", "xpra", "menu-icons"), home):
                    with patch.object(menu_helper, "get_menu_icon_cache_dir", return_value=cache_dir), \
                         patch.object(menu_helper, "load_menu") as load_menu:
                        assert menu_helper.prepare_menu_icon_cache_dir() == ""
                        assert menu_helper.cache_menu_icons() == 0
                        load_menu.assert_not_called()
            finally:
                os.chmod(home, 0o700)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
