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
                 patch.object(menu_helper, "_theme_svg_icon_files", return_value=set()), \
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
                 patch.object(menu_helper, "_theme_svg_icon_files", return_value=set()), \
                 patch.object(menu_helper.icon_util, "load_rsvg", return_value=True), \
                 patch.object(menu_helper.icon_util, "svg_to_png", return_value=PNG_DATA):
                assert menu_helper.cache_menu_icons() == 1

    def test_desktop_entry_icon_names(self):
        from xpra.platform.posix import menu_helper
        with tempfile.TemporaryDirectory() as tmpdir:
            for filename, contents in (
                    ("org.example.Files.desktop", "[Desktop Entry]\nName=Files\nIcon=example-files\nStartupWMClass=example\n"),
                    ("other.desktop", "[Desktop Entry]\nName=Files\nIcon[fr]=localized\nIcon=\n"),
                    ("not-a-desktop-file.txt", "Icon=ignored\n"),
            ):
                with open(os.path.join(tmpdir, filename), "w", encoding="utf8") as f:
                    f.write(contents)
            with patch.object(menu_helper, "LOAD_APPLICATIONS", [tmpdir, os.path.join(tmpdir, "missing")]):
                names = menu_helper.get_desktop_entry_icon_names()
        self.assertEqual(names, {"org.example.Files", "example-files", "example", "other"})

    def test_cache_menu_icons_includes_desktop_entry_theme_icons(self):
        from xpra.platform.posix import menu_helper
        with tempfile.TemporaryDirectory() as tmpdir:
            svg_filename = os.path.join(tmpdir, "app.svg")
            with open(svg_filename, "wb") as f:
                f.write(SVG_DATA)
            cache_dir = os.path.join(tmpdir, "cache")
            with patch.object(menu_helper, "get_menu_icon_cache_dir", return_value=cache_dir), \
                 patch.object(menu_helper, "load_menu", return_value={}), \
                 patch.object(menu_helper, "load_desktop_sessions", return_value={}), \
                 patch.object(menu_helper, "get_desktop_entry_icon_names", return_value={"app"}), \
                 patch.object(menu_helper, "_theme_svg_icon_files", return_value={svg_filename}) as theme_files, \
                 patch.object(menu_helper.icon_util, "load_rsvg", return_value=True), \
                 patch.object(menu_helper.icon_util, "svg_to_png", return_value=PNG_DATA):
                assert menu_helper.cache_menu_icons() == 1
            theme_files.assert_called_once_with({"app"})
            assert os.path.exists(menu_helper.cached_svg_filename(SVG_DATA, cache_dir))

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


class TestMenuEntryKeys(unittest.TestCase):

    def setUp(self):
        from xpra.platform.posix import menu_helper
        if not menu_helper.check_xdg():
            self.skipTest("pyxdg is not installed")
        self.menu_helper = menu_helper
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self.dir = tmpdir.name
        for filename, command in (("org.gnome.Nautilus.desktop", "nautilus"), ("nemo.desktop", "nemo")):
            with open(os.path.join(self.dir, filename), "w", encoding="utf8") as f:
                f.write(f"[Desktop Entry]\nType=Application\nName=Files\nExec={command}\n")
        for attr in ("load_entry_icon", "add_entry_icon"):
            patcher = patch.object(menu_helper, attr, lambda props, *_args, **_kwargs: props)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_same_name(self):
        from xdg.Menu import MenuEntry
        entries = [MenuEntry(filename, self.dir) for filename in ("org.gnome.Nautilus.desktop", "nemo.desktop")]
        submenu = SimpleNamespace(getName=lambda: "Accessories", getEntries=lambda: entries)
        data = self.menu_helper.load_xdg_menu(submenu)
        self.assertEqual({key: entry["command"] for key, entry in data["Entries"].items()}, {
            "org.gnome.Nautilus": "nautilus",
            "nemo": "nemo",
        })

    def test_applications_not_in_the_menu(self):
        menu_data = {"Accessories": {"Entries": {"nemo": {"Name": "Files"}}}}
        with patch.object(self.menu_helper, "LOAD_APPLICATIONS", [self.dir]):
            entries = self.menu_helper.load_applications(menu_data)
        self.assertEqual(list(entries), ["org.gnome.Nautilus"])
        self.assertEqual(entries["org.gnome.Nautilus"]["Name"], "Files")


class TestThemeIconNames(unittest.TestCase):

    def setUp(self):
        from xpra.platform.posix import menu_helper
        self.menu_helper = menu_helper
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        base = tmpdir.name
        for path in ("test-theme/48x48/apps/app.png", "test-theme/scalable/apps/other.svg", "test-theme/unused/hidden.png"):
            os.makedirs(os.path.dirname(os.path.join(base, path)), exist_ok=True)
            with open(os.path.join(base, path), "wb"):
                pass
        theme = SimpleNamespace(name="test-theme", getDirectories=lambda: ("48x48/apps", "scalable/apps", "missing/apps"))
        self.lookups = []

        def lookup_icon(name, _size, theme=None, extensions=()):
            self.lookups.append(name)
            return ""

        icon_theme = SimpleNamespace(icondirs=[base, os.path.join(base, "no-such-dir")], LookupIcon=lookup_icon)
        for attr, value in (
                ("IconTheme", icon_theme),
                ("Config", SimpleNamespace(icon_size=48)),
                ("themes", {"test-theme": theme}),
                ("theme_icon_names", None),
                ("LOAD_FROM_THEME", True),
        ):
            patcher = patch.object(menu_helper, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_names(self):
        self.menu_helper.load_theme_icon_names()
        self.assertEqual(self.menu_helper.theme_icon_names, frozenset(("app", "other")))

    def test_unknown_names_are_skipped(self):
        self.menu_helper.load_theme_icon_names()
        self.menu_helper.find_theme_icon("unknown", "app", "hidden")
        self.assertEqual(self.lookups, ["app"])

    def test_theme_svg_icon_files(self):
        base = self.menu_helper.IconTheme.icondirs[0]
        self.assertEqual(self.menu_helper._theme_svg_icon_files({"app", "other", "hidden", "/abs/icon.svg"}), {
            os.path.join(base, "test-theme", "scalable", "apps", "other.svg"),
            "/abs/icon.svg",
        })

    def test_not_loaded(self):
        self.menu_helper.find_theme_icon("unknown", "app")
        self.assertEqual(self.lookups, ["unknown", "app"])


def main():
    unittest.main()


if __name__ == "__main__":
    main()
