#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 kogeler
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import unittest
from subprocess import Popen, PIPE

from xpra.util import noerr
from xpra.os_util import POSIX
from xpra.client.mixins.window_manager import kill_signalwatcher


@unittest.skipUnless(POSIX, "the signal watcher is only used on posix")
class SignalWatcherTest(unittest.TestCase):

    def test_broken_pipe(self):
        # a watcher which is still running but no longer reads its stdin:
        code = "import os, time; os.close(0); print('ready', flush=True); time.sleep(10)"
        proc = Popen([sys.executable, "-c", code], stdin=PIPE, stdout=PIPE, stderr=PIPE)
        proc.stdout_io_watch = 0
        self.addCleanup(proc.wait)
        self.addCleanup(noerr, proc.kill)
        self.addCleanup(noerr, proc.stdin.close)
        self.assertEqual(proc.stdout.readline(), b"ready\n")
        kill_signalwatcher(proc)
        self.assertTrue(proc.stdin.closed)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
