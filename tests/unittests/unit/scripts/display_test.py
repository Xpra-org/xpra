#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import socket
import tempfile
import unittest
from unittest.mock import patch

from xpra.os_util import WIN32, OSX, POSIX
from xpra.util.env import OSEnvContext
from xpra.scripts.display import (
    X11_SOCKET_DIR,
    x11_display_socket,
    find_x11_display_sockets,
    stat_display_socket,
    find_displays,
    find_wayland_display_sockets,
    get_display_info,
)


class TestConstants(unittest.TestCase):

    def test_x11_socket_dir(self):
        assert X11_SOCKET_DIR == "/tmp/.X11-unix"


class TestX11DisplaySocket(unittest.TestCase):
    """x11_display_socket is a pure string-manipulation function."""

    def test_colon_zero(self):
        assert x11_display_socket(":0") == os.path.join(X11_SOCKET_DIR, "X0")

    def test_colon_ten(self):
        assert x11_display_socket(":10") == os.path.join(X11_SOCKET_DIR, "X10")

    def test_no_colon(self):
        # bare number also works (lstrip(":")  of "0" is "0")
        assert x11_display_socket("0") == os.path.join(X11_SOCKET_DIR, "X0")

    def test_invalid_returns_empty(self):
        assert x11_display_socket(":abc") == ""
        assert x11_display_socket("") == ""
        assert x11_display_socket("notadisplay") == ""

    def test_path_structure(self):
        result = x11_display_socket(":5")
        assert result.endswith("X5")
        assert result.startswith(X11_SOCKET_DIR)


class TestFindX11DisplaySockets(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if WIN32 or OSX:
            raise unittest.SkipTest("X11 socket discovery is POSIX-only")

    def _find(self, tmpdir, **kwargs):
        with patch("xpra.scripts.display.X11_SOCKET_DIR", tmpdir):
            return find_x11_display_sockets(**kwargs)

    def test_nonexistent_dir(self):
        result = self._find("/nonexistent/xpra-test-dir-does-not-exist")
        assert result == {}

    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert self._find(tmpdir) == {}

    def test_sockets_discovered(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for n in (0, 1, 2):
                open(os.path.join(tmpdir, f"X{n}"), "w").close()
            result = self._find(tmpdir)
            assert ":0" in result
            assert ":1" in result
            assert ":2" in result

    def test_paths_are_absolute(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "X0"), "w").close()
            result = self._find(tmpdir)
            assert os.path.isabs(result[":0"])

    def test_non_x_files_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "notasocket"), "w").close()
            open(os.path.join(tmpdir, ".hidden"), "w").close()
            result = self._find(tmpdir)
            assert result == {}

    def test_non_numeric_suffix_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "Xfoo"), "w").close()
            result = self._find(tmpdir)
            assert result == {}

    def test_max_display_no_includes_boundary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for n in (0, 5, 10):
                open(os.path.join(tmpdir, f"X{n}"), "w").close()
            result = self._find(tmpdir, max_display_no=10)
            assert ":0" in result
            assert ":5" in result
            # max_display_no=10 means display_no > 10 is excluded, so :10 stays
            assert ":10" in result

    def test_max_display_no_excludes_higher(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for n in (0, 11):
                open(os.path.join(tmpdir, f"X{n}"), "w").close()
            result = self._find(tmpdir, max_display_no=10)
            assert ":0" in result
            assert ":11" not in result

    def test_zero_max_no_filtering(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for n in (0, 50, 100):
                open(os.path.join(tmpdir, f"X{n}"), "w").close()
            result = self._find(tmpdir, max_display_no=0)
            assert ":0" in result
            assert ":50" in result
            assert ":100" in result


class TestStatDisplaySocket(unittest.TestCase):

    def test_nonexistent_path(self):
        result = stat_display_socket("/nonexistent/xpra-test-socket", timeout=0)
        assert result == {}

    def test_regular_file_rejected(self):
        with tempfile.NamedTemporaryFile() as f:
            result = stat_display_socket(f.name, timeout=0)
            assert result == {}

    def test_directory_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = stat_display_socket(tmpdir, timeout=0)
            assert result == {}

    @unittest.skipUnless(POSIX, "Unix sockets are POSIX-only")
    def test_unix_socket_accepted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sockpath = os.path.join(tmpdir, "test.sock")
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(sockpath)
            srv.listen(1)
            try:
                result = stat_display_socket(sockpath, timeout=0)
                assert "uid" in result, f"uid missing from {result}"
                assert "gid" in result, f"gid missing from {result}"
                assert isinstance(result["uid"], int)
                assert isinstance(result["gid"], int)
            finally:
                srv.close()

    @unittest.skipUnless(POSIX, "Unix sockets are POSIX-only")
    def test_socket_uid_gid_match_current_user(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sockpath = os.path.join(tmpdir, "test.sock")
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(sockpath)
            srv.listen(1)
            try:
                result = stat_display_socket(sockpath, timeout=0)
                assert result["uid"] == os.getuid()
                assert result["gid"] == os.getgid()
            finally:
                srv.close()


class TestFindDisplays(unittest.TestCase):

    def test_returns_dict(self):
        # just verify the return type — actual content depends on the host
        result = find_displays()
        assert isinstance(result, dict)

    @unittest.skipUnless(WIN32 or OSX, "shortcut path is WIN32/OSX only")
    def test_main_on_win32_osx(self):
        assert find_displays() == {"Main": {}}

    @unittest.skipUnless(POSIX and not OSX, "POSIX-only, not OSX")
    def test_posix_returns_display_keyed_dict(self):
        # Each key should look like ":N" (X11) or "wayland-N", or be empty when
        # there are no live displays.  We just verify the structure.
        result = find_displays()
        for key in result:
            assert isinstance(key, str), f"non-string display key: {key!r}"
        for value in result.values():
            assert isinstance(value, dict), f"non-dict display info: {value!r}"

    @unittest.skipUnless(POSIX and not OSX, "POSIX-only, not OSX")
    def test_uid_gid_filtering(self):
        # passing a uid that no socket will match should yield an empty result
        result = find_displays(uid=-9999, gid=-9999)
        assert result == {}


class TestFindWaylandDisplaySockets(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if WIN32 or OSX:
            raise unittest.SkipTest("Wayland discovery is POSIX-only")

    def test_returns_dict(self):
        result = find_wayland_display_sockets()
        assert isinstance(result, dict)

    def test_wayland_env_var_absolute_socket(self):
        """WAYLAND_DISPLAY set to an absolute path pointing at a real socket is discovered."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sockpath = os.path.join(tmpdir, "wayland-test")
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(sockpath)
            srv.listen(1)
            try:
                with OSEnvContext(WAYLAND_DISPLAY=sockpath):
                    with patch("xpra.platform.posix.paths.get_runtime_dir", return_value=tmpdir):
                        result = find_wayland_display_sockets()
                assert sockpath in result.values(), f"{sockpath!r} not found in {result}"
            finally:
                srv.close()

    def test_runtime_dir_glob(self):
        """Sockets matching wayland-* in the runtime dir are discovered."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sockpath = os.path.join(tmpdir, "wayland-0")
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(sockpath)
            srv.listen(1)
            try:
                with OSEnvContext(WAYLAND_DISPLAY=""):
                    with patch("xpra.platform.posix.paths.get_runtime_dir", return_value=tmpdir):
                        result = find_wayland_display_sockets()
                assert "wayland-0" in result, f"wayland-0 not in {result}"
            finally:
                srv.close()

    def test_non_socket_ignored(self):
        """Regular files matching wayland-* are not included."""
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "wayland-0"), "w").close()
            with OSEnvContext(WAYLAND_DISPLAY=""):
                with patch("xpra.platform.posix.paths.get_runtime_dir", return_value=tmpdir):
                    result = find_wayland_display_sockets()
            assert result == {}


class TestGetDisplayInfo(unittest.TestCase):

    def test_non_colon_display_returns_empty(self):
        # wayland and other non-":N" displays return {} on non-OSX
        if OSX:
            raise unittest.SkipTest("OSX returns LIVE for all displays")
        result = get_display_info("wayland-0")
        assert result == {}

    def test_non_colon_display_main(self):
        if OSX:
            raise unittest.SkipTest("OSX returns LIVE for all displays")
        result = get_display_info("Main")
        assert result == {}

    @unittest.skipUnless(OSX, "OSX-only shortcut")
    def test_osx_always_live(self):
        result = get_display_info(":0")
        assert result.get("state") == "LIVE"


def main():
    unittest.main()


if __name__ == "__main__":
    main()
