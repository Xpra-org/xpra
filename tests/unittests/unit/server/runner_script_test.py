#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from xpra.server import runner_script


class RunnerScriptTest(unittest.TestCase):

    def test_quote_and_environment_script(self):
        self.assertEqual(runner_script.sh_quotemeta("a'b"), "'a'\\''b'")
        script = runner_script.xpra_env_shell_script(("~/socket dir",), {
            "PATH": "/bin:/usr/bin:/bin", "HOME": "/home/test", "IGNORED": "no",
        })
        self.assertIn("PATH='/bin:/usr/bin':\"$PATH\"", script)
        self.assertNotIn("IGNORED", script)
        self.assertIn("XPRA_SOCKET_DIR='", script)
        self.assertNotIn('XPRA_SOCKET_DIR="\'', script)

    def test_runner_script(self):
        with patch.object(runner_script, "OSX", False), \
                patch.object(runner_script.sys, "executable", "/usr/bin/python3"):
            script = runner_script.xpra_runner_shell_script("/opt/xpra script", "/tmp/start dir")
        self.assertIn("cd '/tmp/start dir'", script)
        self.assertIn("_XPRA_PYTHON='/usr/bin/python3'", script)
        self.assertIn("_XPRA_SCRIPT='/opt/xpra script'", script)
        self.assertIn("exec xpra", script)

    def test_write_runner_scripts(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("xpra.platform.paths.get_script_bin_dirs", return_value=(directory,)):
            runner_script.write_runner_shell_scripts("first")
            path = os.path.join(directory, "run-xpra")
            self.assertEqual(Path(path).read_text(encoding="utf8"), "first")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o700)
            runner_script.write_runner_shell_scripts("second", overwrite=False)
            self.assertEqual(Path(path).read_text(encoding="utf8"), "first")
            runner_script.write_runner_shell_scripts("second", overwrite=True)
            self.assertEqual(Path(path).read_text(encoding="utf8"), "second")


if __name__ == "__main__":
    unittest.main()
