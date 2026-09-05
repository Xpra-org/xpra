#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import shutil
import tempfile
import unittest

from xpra.scripts.config import read_xpra_conf


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


def main():
    unittest.main()


if __name__ == "__main__":
    main()
