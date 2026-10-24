#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
PT_DENY_ATTACH cannot be undone, so the tests apply it in a subprocess.
"""

import json
import os
import subprocess
import sys
import unittest

OSX = sys.platform.startswith("darwin")

# runs in the hardened subprocess, prints a json dict:
HARDENED = """
import json
import resource
from xpra.platform.darwin import security as s
from xpra.platform.security import harden_process
traced = s.is_traced()
harden_process()
harden_process()
print(json.dumps({
    "traced": traced,
    "core": resource.getrlimit(resource.RLIMIT_CORE),
}))
"""

# PT_ATTACHEXC=14, see <sys/ptrace.h>:
ATTACH = """
import ctypes, sys
libc = ctypes.CDLL(None, use_errno=True)
libc.ptrace.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int)
r = libc.ptrace(14, int(sys.argv[1]), None, 0)
print(ctypes.get_errno() if r != 0 else 0)
"""


def python_env() -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(sys.path)
    return env


def run_python(*args) -> str:
    return subprocess.run([sys.executable, "-c", *args],
                          capture_output=True, text=True, check=True, env=python_env()).stdout


@unittest.skipUnless(OSX, "macOS only")
class DarwinSecurityTest(unittest.TestCase):

    def test_is_traced(self):
        from xpra.platform.darwin.security import is_traced
        self.assertIsInstance(is_traced(), bool)

    def test_harden_process(self):
        result = json.loads(run_python(HARDENED))
        self.assertFalse(result["traced"])
        self.assertEqual(result["core"], [0, 0])

    def test_deny_attach(self):
        # the hardened process waits on stdin until we have tried to attach to it:
        script = "from xpra.platform.security import harden_process; harden_process(); print('ok', flush=True); input()"
        proc = subprocess.Popen([sys.executable, "-c", script], env=python_env(),
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(proc.stdout.readline().strip(), "ok")
            # the kernel either refuses the attach or kills the tracer with SIGSEGV:
            attach = subprocess.run([sys.executable, "-c", ATTACH, str(proc.pid)],
                                    capture_output=True, text=True, env=python_env())
            attached = attach.returncode == 0 and attach.stdout.strip() == "0"
            self.assertFalse(attached, "attaching to the hardened process should fail")
            self.assertIsNone(proc.poll(), "the hardened process should still be running")
        finally:
            proc.kill()
            proc.wait()


def main():
    unittest.main()


if __name__ == '__main__':
    main()
