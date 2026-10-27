#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from xpra.os_util import POSIX, OSX

# stands in for the `xpra` script started by `_proxy_start`,
# which daemonizes and only writes the display number to `--displayfd` once the server is ready:
FAKE_SERVER = """
import os, sys
fd = int([arg for arg in sys.argv if arg.startswith("--displayfd=")][0].split("=", 1)[1])
if os.environ.get("FAKE_SERVER_FAIL"):
    sys.exit(0)
os.write(fd, os.environ.get("FAKE_SERVER_DISPLAY", "100").encode() + b"\\n")
"""


@unittest.skipUnless(POSIX and not OSX, "displayfd is only used on Linux and similar")
class TestStartServerSubprocess(unittest.TestCase):

    def setUp(self):
        fd, self.script = tempfile.mkstemp(suffix=".py")
        with os.fdopen(fd, "w") as f:
            f.write(f"#!{sys.executable}\n{FAKE_SERVER}")
        os.chmod(self.script, 0o700)
        self.addCleanup(os.unlink, self.script)

    @staticmethod
    def make_opts():
        from xpra.scripts.parsing import make_defaults_struct
        opts = make_defaults_struct()
        opts.socket_dirs = [tempfile.gettempdir()]
        return opts

    def start(self, args, env=None):
        from xpra.scripts import proxy
        found = []

        def identify_new_socket(proc, dotxpra, existing, matching_display, *_args):
            found.append(matching_display)
            return "/fake/socket", matching_display
        with patch.object(proxy, "identify_new_socket", side_effect=identify_new_socket), \
                patch.object(proxy, "get_start_server_args", return_value=[]):
            proxy.start_server_subprocess(self.script, args, "seamless", self.make_opts(),
                                          env=dict(os.environ, **(env or {})))
        return found

    def test_display_from_displayfd(self):
        self.assertEqual(self.start([], {"FAKE_SERVER_DISPLAY": "42"}), [":42"])

    def test_explicit_display(self):
        # the display we asked for is the one we look for, whatever the server writes:
        self.assertEqual(self.start([":100"], {"FAKE_SERVER_DISPLAY": "100"}), [":100"])

    def test_fails_fast(self):
        from xpra.config import InitExit
        for args in ([], [":100"]):
            start = time.monotonic()
            with self.assertRaises(InitExit):
                self.start(args, {"FAKE_SERVER_FAIL": "1"})
            # not `WAIT_SERVER_TIMEOUT`:
            self.assertLess(time.monotonic() - start, 10, f"failure detected too slowly with {args=}")


class TestStartOnExisting(unittest.TestCase):

    def run_start(self, start=(), start_child=(), returncode=0, default_start=()):
        from subprocess import CompletedProcess
        from xpra.scripts import proxy
        opts = TestStartServerSubprocess.make_opts()
        defaults = TestStartServerSubprocess.make_opts()
        opts.start = list(default_start) + list(start)
        opts.start_child = list(start_child)
        defaults.start = list(default_start)
        defaults.start_child = []
        result = CompletedProcess([], returncode, b"", b"new command started with pid=1\n")
        with patch("subprocess.run", return_value=result) as run, \
                patch.object(proxy, "stderr_print") as stderr_print:
            proxy.start_commands_on_existing("/usr/bin/xpra", ":100", opts, defaults)
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
