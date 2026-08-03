#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest

from xpra.util.objects import AdHocStruct
from unit.server.subsystem.servermixintest_util import ServerMixinTest


class MMAPMixinTest(ServerMixinTest):

    def _test_mmap(self, opts):
        from xpra.server.subsystem.mmap import MMAP_Server
        self._test_mixin_class(MMAP_Server, opts)
        assert self.mixin.get_info(self.protocol).get("mmap", {}).get("supported") is True

    def test_mmap_on(self):
        opts = AdHocStruct()
        opts.mmap = "on"
        self._test_mmap(opts)
        assert not self.mixin.dirs and not self.mixin.files

    def test_mmap_path(self):
        opts = AdHocStruct()
        opts.mmap = tempfile.gettempdir()+"/mmap-test-file"
        self._test_mmap(opts)
        # a path which is not a directory is used as-is:
        assert self.mixin.files == (opts.mmap, )
        assert not self.mixin.dirs

    def test_mmap_paths(self):
        # a mixture of directories and files, in any order:
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            filename = os.path.join(d1, "mmap-test-file")
            opts = AdHocStruct()
            opts.mmap = os.path.pathsep.join((d1, filename, d2))
            self._test_mmap(opts)
            assert self.mixin.dirs == (d1, d2), f"unexpected dirs: {self.mixin.dirs}"
            assert self.mixin.files == (filename, ), f"unexpected files: {self.mixin.files}"
            info = self.mixin.get_info(self.protocol).get("mmap", {})
            assert info.get("dirs") == (d1, d2)
            assert info.get("files") == (filename, )

    def test_mmap_relative_path(self):
        # relative paths are not usable and must be ignored:
        opts = AdHocStruct()
        opts.mmap = os.path.pathsep.join((tempfile.gettempdir(), "relative-path"))
        self._test_mmap(opts)
        assert self.mixin.dirs == (tempfile.gettempdir(), )
        assert not self.mixin.files


def main():
    unittest.main()


if __name__ == '__main__':
    main()
