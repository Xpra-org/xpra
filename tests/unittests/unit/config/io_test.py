#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from xpra.config import io
from xpra.config.io import parse_config_lines, read_config, read_xpra_conf, read_xpra_defaults, save_config
from xpra.config.types import dict_to_config


class ConfigIOTest(unittest.TestCase):

    def test_text_grammar(self):
        text = "\n # comment\n ! comment\ninvalid\n=value\n title = one=two \nstart = first\nstart = second\nstart = third\nempty =\n"
        self.assertEqual(parse_config_lines(iter(text.splitlines(True))),
                         {"title": "one=two", "start": ["first", "second", "third"], "empty": ""})

    def test_continuations(self):
        self.assertEqual(parse_config_lines(["title=first\\\n", "# comment\n", "second\\\n", "third\n"]), {"title": "first second third"})
        self.assertEqual(parse_config_lines(["title=last\\\n"]), {"title": "last"})

    def test_repeated_empty_value_preserves_existing_semantics(self):
        self.assertEqual(parse_config_lines(["title=\n", "title=second\n"]), {"title": "second"})

    def test_save_and_read(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "settings.conf"
            save_config(str(file), dict_to_config({"title": "test", "quality": 72, "extra": "custom"}),
                        ["title", "quality", "extra"], extras_types={"extra": str})
            self.assertEqual(read_config(str(file)), {"title": "test", "quality": "72", "extra": "custom"})
            with self.assertRaises(ValueError):
                save_config(str(file), dict_to_config({}), ["unknown"])

    def test_missing_and_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(read_config(directory), {})
            self.assertEqual(read_config(str(Path(directory) / "missing")), {})
            self.assertEqual(read_xpra_conf(str(Path(directory) / "missing")), {})
            self.assertEqual(io.conf_files(str(Path(directory) / "missing")), [])

    def test_file_and_directory_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "conf.d").mkdir()
            (root / "xpra.conf").write_text("title=main\nquality=20\n")
            (root / "conf.d" / "90-last.conf").write_text("title=last\n")
            (root / "conf.d" / "05-first.conf").write_text("title=first\n")
            (root / "conf.d" / "ignored.txt").write_text("title=ignored\n")
            self.assertEqual(read_xpra_conf(directory), {"title": "last", "quality": "20"})
            self.assertEqual([Path(f).name for f in io.conf_files(directory)], ["05-first.conf", "90-last.conf", "xpra.conf"])
            (root / "xpra.conf").unlink()
            self.assertEqual([Path(f).name for f in io.conf_files(directory)], ["05-first.conf", "90-last.conf"])

    def test_defaults_directory_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folders = [root / name for name in ("application", "system", "user")]
            for index, folder in enumerate(folders):
                folder.mkdir()
                (folder / "xpra.conf").write_text(f"title={index}\n")
            with patch.object(io, "get_xpra_defaults_dirs", return_value=[str(f) for f in folders]), \
                 patch.object(io, "may_create_user_config") as create:
                self.assertEqual(read_xpra_defaults("tester", 123, 456), {"title": "2"})
            create.assert_called_once_with()

    def test_diagnostics_can_be_redirected(self):
        with patch("xpra.config.debug") as debug:
            self.assertEqual(parse_config_lines(["title=test"]), {"title": "test"})
        self.assertTrue(debug.called)

    def test_user_template_creation_and_existing_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "new"
            with patch("xpra.platform.paths.get_user_conf_dirs", return_value=[str(folder)]):
                io.may_create_user_config()
                file = folder / "xpra.conf"
                self.assertIn("# xpra user configuration file", file.read_text())
                file.write_text("title=keep\n")
                io.may_create_user_config()
                self.assertEqual(file.read_text(), "title=keep\n")

    def test_failed_template_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "new"
            with patch("xpra.platform.paths.get_user_conf_dirs", return_value=[str(folder)]), \
                 patch.object(io.os, "makedirs", side_effect=PermissionError), patch("xpra.config.debug") as debug:
                io.may_create_user_config()
            self.assertFalse(folder.exists())
            self.assertIn("failed to create", debug.call_args.args[0])

    def test_default_directory_discovery_order(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("xpra.platform.paths.get_default_conf_dirs", return_value=["", directory]), \
                 patch("xpra.platform.paths.get_system_conf_dirs", return_value=[str(Path(directory) / "missing")]), \
                 patch("xpra.platform.paths.get_user_conf_dirs", return_value=[directory]) as user:
                self.assertEqual(io.get_xpra_defaults_dirs("tester", 123, 456), [directory, directory])
            user.assert_called_once_with(123)

    def test_property_diagnostics_include_filename(self):
        with patch.object(io, "DEBUG_CONFIG_PROPERTIES", ["title"]), patch("xpra.log.Logger") as logger:
            self.assertEqual(parse_config_lines(["title=test"], "supplied.conf"), {"title": "test"})
        self.assertIn("supplied.conf", logger.return_value.info.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
