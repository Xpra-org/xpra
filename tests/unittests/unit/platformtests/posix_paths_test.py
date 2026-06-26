#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from xpra.platform.posix import paths


class PosixPathsTest(unittest.TestCase):

    def test_prefers_xdg_user_dir_command(self):
        with patch("xpra.platform.posix.paths._get_xdg_download_dir", return_value="/command"), \
             patch("xpra.platform.posix.paths._get_user_dirs_download_dir", return_value="/config"), \
             patch("xpra.platform.posix.paths.os.path.exists", return_value=True):
            assert paths.do_get_download_dir() == "/command"

    def test_uses_user_dirs_config_when_command_unavailable(self):
        with patch("xpra.platform.posix.paths._get_xdg_download_dir", return_value=""), \
             patch("xpra.platform.posix.paths._get_user_dirs_download_dir", return_value="/config"), \
             patch("xpra.platform.posix.paths.os.path.exists", return_value=True):
            assert paths.do_get_download_dir() == "/config"

    def test_uses_existing_home_downloads_fallback(self):
        with patch("xpra.platform.posix.paths._get_xdg_download_dir", return_value=""), \
             patch("xpra.platform.posix.paths._get_user_dirs_download_dir", return_value=""):
            with TemporaryDirectory() as tmpdir:
                home = os.path.join(tmpdir, "home")
                downloads = os.path.join(home, "Downloads")
                os.makedirs(downloads)
                with patch.dict(os.environ, {"HOME": home}, clear=False):
                    assert paths.do_get_download_dir() == "~/Downloads"

    def test_falls_back_to_tmp(self):
        with patch("xpra.platform.posix.paths._get_xdg_download_dir", return_value=""), \
             patch("xpra.platform.posix.paths._get_user_dirs_download_dir", return_value=""):
            with TemporaryDirectory() as tmpdir:
                home = os.path.join(tmpdir, "home")
                os.makedirs(home)
                with patch.dict(os.environ, {"HOME": home}, clear=False):
                    assert paths.do_get_download_dir() == "/tmp"

    def test_parses_user_dirs_download_entry(self):
        with TemporaryDirectory() as tmpdir:
            config_home = os.path.join(tmpdir, "config")
            os.makedirs(config_home)
            with open(os.path.join(config_home, "user-dirs.dirs"), "w", encoding="utf-8") as f:
                f.write('XDG_DOWNLOAD_DIR="$HOME/Telechargements"\n')
            home = os.path.join(tmpdir, "home")
            os.makedirs(home)
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": config_home, "HOME": home}, clear=False):
                assert paths._get_user_dirs_download_dir() == "$HOME/Telechargements"


def main():
    unittest.main()


if __name__ == '__main__':
    main()
