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


def main():
    unittest.main()


if __name__ == '__main__':
    main()
