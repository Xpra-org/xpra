#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from xpra.util import config


class ConfigTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="xpra-config-test")
        self.user_dir = os.path.join(self.tmpdir, "user")
        self.system_dir = os.path.join(self.tmpdir, "system")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @contextmanager
    def config_dirs(self, user_dirs: list[str], admin=False):
        with patch.multiple("xpra.platform.paths",
                            get_user_conf_dirs=lambda *_args: user_dirs,
                            get_system_conf_dirs=lambda: [self.system_dir]), \
                patch.object(config, "is_admin", return_value=admin):
            yield

    def user_config_file(self) -> str:
        return os.path.join(self.user_dir, "conf.d", config.CONFIGURE_TOOL_CONFIG)

    def system_config_file(self) -> str:
        return os.path.join(self.system_dir, "conf.d", config.CONFIGURE_TOOL_CONFIG)

    def test_user_config_file(self):
        with self.config_dirs([self.user_dir]):
            self.assertEqual(config.get_user_config_file(), self.user_config_file())

    def test_admin_uses_the_system_config(self):
        # administrators modify the system configuration - see #5032
        # (and the root user has no configuration directory of its own)
        for user_dirs in ([self.user_dir], []):
            with self.subTest(user_dirs=user_dirs), self.config_dirs(user_dirs, admin=True):
                self.assertEqual(config.get_user_config_file(), self.system_config_file())

    def test_system_config_file_without_user_dirs(self):
        with self.config_dirs([]):
            self.assertEqual(config.get_user_config_file(), self.system_config_file())
            self.assertEqual(config.parse_user_config_file(), {})
            conf_file = config.update_config_attribute("xvfb", "Xdummy")
            self.assertEqual(conf_file, self.system_config_file())
            self.assertTrue(os.path.exists(conf_file))
            self.assertEqual(config.parse_user_config_file().get("xvfb"), "Xdummy")
            config.unset_config_attribute("xvfb")
            self.assertEqual(config.parse_user_config_file(), {})

    def test_save_failure(self):
        conf_dir = os.path.join(self.user_dir, "conf.d")
        os.makedirs(conf_dir, mode=0o500)
        try:
            with self.config_dirs([self.user_dir]):
                self.assertEqual(config.update_config_attribute("xvfb", "Xdummy"), "")
        finally:
            os.chmod(conf_dir, 0o700)

    def test_config_env(self):
        with self.config_dirs([self.user_dir]):
            config.update_config_env("XPRA_SHADOW_BACKEND", "pipewire")
            self.assertEqual(config.get_config_env("XPRA_SHADOW_BACKEND"), "pipewire")
            self.assertEqual(config.get_config_env("XPRA_NOT_SET"), "")


def main():
    unittest.main()


if __name__ == "__main__":
    main()
