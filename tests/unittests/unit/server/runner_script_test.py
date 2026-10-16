#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

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


if __name__ == "__main__":
    unittest.main()
