#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import shutil
import tempfile
import unittest

from unittest.mock import patch

from xpra.scripts.config import (
    read_xpra_conf, fixup_keyboard, fixup_options, get_default_landlock, dict_to_validated_config,
)
from xpra.util.parsing import FALSE_OPTIONS, TRUE_OPTIONS


class LandlockConfigTest(unittest.TestCase):

    def test_environment_aliases(self):
        for values, expected in ((FALSE_OPTIONS, "no"), (TRUE_OPTIONS, "default"),
                                 (("default",), "default"), (("strict",), "strict"), (("",), "no")):
            for value in values:
                with self.subTest(value=value), patch.dict(os.environ, {"XPRA_LANDLOCK": str(value).upper()}):
                    self.assertEqual(get_default_landlock(), expected)

    def test_configuration_aliases(self):
        for values, expected in ((FALSE_OPTIONS, "no"), (TRUE_OPTIONS, "default"),
                                 (("default",), "default"), (("strict",), "strict")):
            for value in values:
                with self.subTest(value=value):
                    options = dict_to_validated_config({"landlock": str(value).upper()})
                    fixup_options(options)
                    self.assertEqual(options.landlock, expected)

    def test_configuration_overrides_environment(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(os.environ, {"XPRA_LANDLOCK": "strict"}), \
             patch("xpra.scripts.config.GLOBAL_DEFAULTS", None):
            with open(os.path.join(directory, "xpra.conf"), "w", encoding="utf8") as config:
                config.write("landlock = OFF\n")
            options = dict_to_validated_config(read_xpra_conf(directory))
            fixup_options(options)
            self.assertEqual(options.landlock, "no")


class ReadConfTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="xpra-conf-test")
        self.conf_d = os.path.join(self.tmpdir, "conf.d")
        os.mkdir(self.conf_d)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def write(self, filename: str, contents: str) -> None:
        with open(os.path.join(self.tmpdir, filename), "w", encoding="utf8") as f:
            f.write(contents)

    def test_conf_d_order(self):
        # the numeric prefix decides which value wins,
        # no matter what order the directory happens to be read in:
        self.write("xpra.conf", "xvfb = Xvfb\nmode = seamless\n")
        for filename in ("55_server_x11.conf", "05_features.conf", "90_configure_tool.conf", "12_network.conf"):
            self.write(os.path.join("conf.d", filename), f"xvfb = {filename}\n")
        conf = read_xpra_conf(self.tmpdir)
        self.assertEqual(conf.get("xvfb"), "90_configure_tool.conf")
        # `xpra.conf` values are only overriden by the `conf.d` files that set them:
        self.assertEqual(conf.get("mode"), "seamless")

    def test_missing_dir(self):
        self.assertEqual(read_xpra_conf(os.path.join(self.tmpdir, "does-not-exist")), {})


class FixupKeyboardTest(unittest.TestCase):

    @staticmethod
    def fixup(layouts, variants):
        class Options:
            keyboard_backend = "auto"
            keyboard_raw = "no"
        options = Options()
        options.keyboard_layouts = layouts
        options.keyboard_variants = variants
        fixup_keyboard(options)
        return options.keyboard_layouts, options.keyboard_variants

    def test_csv(self):
        # `str` is also a `Sequence`, so this used to be split into characters:
        self.assertEqual(self.fixup("fr,us", "oss,"), (["fr", "us"], ["oss", ""]))

    def test_single_value(self):
        self.assertEqual(self.fixup("fr", ""), (["fr"], []))

    def test_list_is_kept(self):
        self.assertEqual(self.fixup(["fr", "us"], []), (["fr", "us"], []))

    def test_duplicates_and_whitespace(self):
        self.assertEqual(self.fixup(" fr , us , fr ", "")[0], ["fr", "us"])


def main():
    unittest.main()


if __name__ == "__main__":
    main()
