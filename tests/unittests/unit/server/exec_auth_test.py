#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import shlex
import subprocess
import sys
import unittest
from unittest.mock import patch

from xpra.child_reaper import ChildReaper
from xpra.server.auth import exec_auth
from xpra.util import typedict


@unittest.skipUnless(hasattr(os, "waitid"), "os.waitid is not available")
class ExecAuthTest(unittest.TestCase):

    def check_reaped_auth(self, command, expected):
        # Avoid registering signal handlers or timers for this private reaper.
        reaper = ChildReaper.__new__(ChildReaper)
        reaper._quit = None
        reaper._proc_info = []

        class ReapedPopen(subprocess.Popen):
            def __init__(self, cmd):
                super().__init__(cmd, stdin=subprocess.PIPE)

            def __exit__(self, *args):
                self.stdin.write(b"x")
                self.stdin.flush()
                os.waitid(os.P_PID, self.pid, os.WEXITED | os.WNOWAIT)
                with self._waitpid_lock:
                    reaper.reap()
                return super().__exit__(*args)

        for timeout in (0, 5):
            with self.subTest(timeout=timeout):
                auth = exec_auth.Authenticator(
                    command="{} -c {}".format(shlex.quote(sys.executable), shlex.quote(command)),
                    connection="test", timeout=timeout,
                )
                with patch.object(exec_auth, "Popen", ReapedPopen), \
                        patch.object(exec_auth, "getChildReaper", return_value=reaper), \
                        patch.object(exec_auth, "OSX", False), \
                        patch.object(exec_auth.GLib, "timeout_add", return_value=1), \
                        patch.object(exec_auth.GLib, "source_remove"), \
                        patch.object(exec_auth.GLib, "idle_add", side_effect=lambda cb, *args: cb(*args)):
                    result = auth.default_authenticate_check(typedict())
                # Popen lost the actual status; auth must use the reaper's record.
                self.assertEqual(auth.proc.returncode, 0)
                self.assertEqual(result, expected)
                reaper.cleanup()

    def test_reaped_failure_is_rejected(self):
        self.check_reaped_auth("import sys; sys.stdin.read(1); sys.exit(7)", False)

    def test_reaped_signal_is_rejected(self):
        self.check_reaped_auth(
            "import os, signal, sys; sys.stdin.read(1); os.kill(os.getpid(), signal.SIGTERM)", False,
        )

    def test_reaped_success_is_accepted(self):
        self.check_reaped_auth("import sys; sys.stdin.read(1); sys.exit(0)", True)


if __name__ == "__main__":
    unittest.main()
