#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from subprocess import CompletedProcess
from unittest.mock import patch

from xpra.scripts import main as scripts_main
from xpra.scripts.config import make_defaults_struct


class TestStartOnExisting(unittest.TestCase):

    def run_start(self, start=(), start_child=(), returncode=0, default_start=()):
        opts = make_defaults_struct()
        defaults = make_defaults_struct()
        opts.start = list(default_start) + list(start)
        opts.start_child = list(start_child)
        defaults.start = list(default_start)
        defaults.start_child = []
        result = CompletedProcess([], returncode, b"", b"new command started with pid=1\n")
        with patch.object(scripts_main, "run", return_value=result) as run, \
                patch.object(scripts_main, "stderr_print") as stderr_print:
            scripts_main.start_commands_on_existing("/usr/bin/xpra", ":100", opts, defaults)
        return run, stderr_print

    def test_commands(self):
        run, _ = self.run_start(start=["xterm -T 'a title'"], start_child=["xclock"], default_start=["ibus-daemon"])
        cmds = [c.args[0] for c in run.call_args_list]
        # the defaults from the config files are not started again:
        self.assertEqual(cmds, [
            ["/usr/bin/xpra", "control", ":100", "start", "--", "xterm", "-T", "a title"],
            ["/usr/bin/xpra", "control", ":100", "start-child", "--", "xclock"],
        ])
        for c in run.call_args_list:
            # our stdout is the connection to the client:
            self.assertTrue(c.kwargs.get("capture_output"))
            self.assertNotIn("stdout", c.kwargs)

    def test_nothing_to_start(self):
        run, _ = self.run_start(default_start=["ibus-daemon"])
        run.assert_not_called()

    def test_failure_reported(self):
        _, stderr_print = self.run_start(start=["nosuchcommand"], returncode=1)
        messages = " ".join(str(c.args[0]) for c in stderr_print.call_args_list)
        self.assertIn("failed to start 'nosuchcommand' on display :100", messages)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
