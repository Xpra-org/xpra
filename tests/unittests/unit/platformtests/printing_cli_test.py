#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 kogeler
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

import xpra
from xpra.os_util import POSIX, OSX
from xpra.platform import printing


class PrintingCliTest(unittest.TestCase):

    def test_info_does_not_watch_printers(self):
        # a one-shot command does not use printer change notifications
        with (
            patch.object(printing, "init_printing") as init,
            patch.object(printing, "get_printers", return_value={}),
            patch.object(printing, "get_info", return_value={}),
            patch("xpra.log.enable_color"),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(printing.main(["printing-info"]), 0)
        init.assert_not_called()

    @unittest.skipUnless(POSIX and not OSX, "uses the pycups backend")
    def test_info_exits_without_system_bus(self):
        try:
            import cups  # noqa: F401
        except ImportError:
            self.skipTest("pycups is not installed")
        with tempfile.TemporaryDirectory() as tmpdir:
            env = os.environ.copy()
            # run the same xpra code as this test, not whatever is installed:
            root = os.path.dirname(os.path.dirname(xpra.__file__))
            env["PYTHONPATH"] = os.pathsep.join(filter(None, (root, env.get("PYTHONPATH"))))
            # without a system bus, pycups falls back to polling for printer changes:
            env["DBUS_SYSTEM_BUS_ADDRESS"] = f"unix:path={tmpdir}/no-bus"
            # and without a cups server, the result does not depend on this host:
            env["CUPS_SERVER"] = f"{tmpdir}/no-cups"
            env["LC_ALL"] = "C"
            try:
                proc = subprocess.run([sys.executable, "-m", "xpra.platform.printing"],
                                      env=env, capture_output=True, text=True, timeout=10)
            except subprocess.TimeoutExpired:
                self.fail("printing-info did not exit")
        self.assertIn("failed to connect to server", proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
