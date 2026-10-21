#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from contextlib import contextmanager
from unittest.mock import Mock, patch

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
        # Do not depend on the uid running the tests respecting Unix permission bits.
        with self.config_dirs([self.user_dir]), patch.object(config, "log"):
            with patch.object(config.os, "makedirs", side_effect=PermissionError("cannot create")):
                self.assertEqual(config.update_config_attribute("xvfb", "Xdummy"), "")
            # a directory where the file should be makes `open` fail, even for root,
            # and unlike patching `builtins.open`, this also works when the module is compiled:
            os.makedirs(self.user_config_file())
            self.assertEqual(config.save_user_config_file({"xvfb": "Xdummy"}), "")

    def test_config_env(self):
        with self.config_dirs([self.user_dir]):
            config.update_config_env("XPRA_SHADOW_BACKEND", "pipewire")
            self.assertEqual(config.get_config_env("XPRA_SHADOW_BACKEND"), "pipewire")
            self.assertEqual(config.get_config_env("XPRA_NOT_SET"), "")

    def test_lists_nested_values_and_boolean_updates_round_trip(self):
        with self.config_dirs([self.user_dir]):
            config.save_user_config_file({"items": ["one", "two"], "number": 4, "env": {"KEY": "value"}})
            self.assertEqual(config.parse_user_config_file(), {"items": ["one", "two"], "number": "4", "env": {"KEY": "value"}})
            config.update_config_attributes({"enabled": True, "disabled": False})
            values = config.parse_user_config_file()
            self.assertEqual(values["enabled"], "yes")
            self.assertEqual(values["disabled"], "no")
            self.assertEqual(values["items"], ["one", "two"])

    def test_invalid_env_is_replaced_when_updated(self):
        with self.config_dirs([self.user_dir]), patch.object(config, "log"):
            config.save_user_config_file({"env": "invalid"})
            self.assertEqual(config.get_config_env("KEY"), "")
            config.update_config_env("KEY", 42)
            self.assertEqual(config.get_config_env("KEY"), "42")

    def test_unsetting_missing_options_does_not_write(self):
        with self.config_dirs([self.user_dir]), patch.object(config, "save_user_config_file") as save:
            config.unset_config_attributes(["missing"])
            save.assert_not_called()

    def test_configuration_callback_is_scheduled_after_loading(self):
        callback = Mock()
        defaults = object()
        glib = SimpleNamespace(idle_add=Mock())
        with patch.object(config, "start_thread") as start, patch.object(config, "make_defaults_struct", return_value=defaults), \
                patch.object(config, "gi_import", return_value=glib):
            config.with_config(callback)
            callback.assert_not_called()
            load = start.call_args.args[0]
            start.assert_called_once_with(load, "load-config", daemon=True)
            glib.idle_add.assert_not_called()
            load()
            glib.idle_add.assert_called_once_with(callback, defaults)
            callback.assert_not_called()

    def test_legacy_configuration_is_migrated_once(self):
        directory = Path(self.user_dir) / "conf.d"
        directory.mkdir(parents=True)
        old = directory / config.OLD_CONFIGURE_TOOL_CONFIG
        new = directory / config.CONFIGURE_TOOL_CONFIG
        old.write_text("xvfb = Xdummy\n")
        with self.config_dirs([self.user_dir]):
            config.may_migrate()
            self.assertFalse(old.exists())
            self.assertEqual(new.read_text(), "xvfb = Xdummy\n")
            old.write_text("xvfb = stale\n")
            config.may_migrate()
            self.assertEqual(old.read_text(), "xvfb = stale\n")
            self.assertEqual(new.read_text(), "xvfb = Xdummy\n")

    def test_migration_failure_keeps_the_legacy_file(self):
        directory = Path(self.user_dir) / "conf.d"
        directory.mkdir(parents=True)
        old = directory / config.OLD_CONFIGURE_TOOL_CONFIG
        old.write_text("xvfb = Xdummy\n")
        with self.config_dirs([self.user_dir]), patch.object(config.os, "rename", side_effect=OSError("read only")):
            config.may_migrate()
        self.assertTrue(old.exists())
        self.assertFalse((directory / config.CONFIGURE_TOOL_CONFIG).exists())


def main():
    unittest.main()


if __name__ == "__main__":
    main()
