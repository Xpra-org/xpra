#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from xpra.scripts.server import create_runtime_dir, is_splash_enabled


class TestMain(unittest.TestCase):

    def test_splash_enabled(self):
        assert is_splash_enabled("foo", True, True, ":10") is False, "splash should not be enabled for daemons"
        assert is_splash_enabled("foo", False, False, ":10") is False, "splash should not be enabled for splash=False"
        assert is_splash_enabled("foo", False, True, ":10") is True, "splash should be enabled for splash=True"

    def test_create_runtime_dir_concurrently(self):
        uid, gid = os.getuid(), os.getgid()
        with tempfile.TemporaryDirectory() as parent, \
                patch("xpra.scripts.server.POSIX", True), \
                patch("xpra.scripts.server.getuid", return_value=0), \
                patch("xpra.scripts.server.os.lchown"):
            runtime_dir = os.path.join(parent, str(uid))
            with ThreadPoolExecutor(max_workers=8) as executor:
                result = list(executor.map(lambda _: create_runtime_dir(runtime_dir, uid, gid), range(8)))
            assert result == [runtime_dir] * 8
            assert os.path.isdir(os.path.join(runtime_dir, "xpra"))

    def test_root_does_not_create_a_runtime_dir(self):
        with patch("xpra.scripts.server.getuid", return_value=0), \
                patch("xpra.scripts.server.os.mkdir") as mkdir:
            assert create_runtime_dir("", 0, 0) == ""
        mkdir.assert_not_called()


def main():
    unittest.main()


if __name__ == '__main__':
    main()
