#!/usr/bin/env python3

import os
import unittest
from unittest.mock import patch

from xpra.platform.posix import paths
from xpra.util.env import osexpand


class PosixPathsTest(unittest.TestCase):

    def test_root_does_not_fallback_to_run_user_0(self):
        with patch.dict(os.environ, {}, clear=False), \
                patch("xpra.platform.posix.paths.os.geteuid", return_value=0), \
                patch("xpra.platform.posix.paths.sys.platform", "linux"):
            os.environ.pop("XDG_RUNTIME_DIR", None)
            assert paths.get_runtime_dir() == ""

    def test_root_can_expand_the_runtime_dir_for_another_user(self):
        with patch.dict(os.environ, {}, clear=False), \
                patch("xpra.platform.posix.paths.os.geteuid", return_value=0), \
                patch("xpra.platform.posix.paths.os.path.exists", return_value=True), \
                patch("xpra.platform.posix.paths.os.path.isdir", return_value=True), \
                patch("xpra.platform.posix.paths.sys.platform", "linux"):
            os.environ.pop("XDG_RUNTIME_DIR", None)
            assert osexpand("$XDG_RUNTIME_DIR/xpra", uid=1000) == "/run/user/1000/xpra"


if __name__ == "__main__":
    unittest.main()
