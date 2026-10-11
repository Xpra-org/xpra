#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
The restrictions cannot be undone, so each test applies them in a subprocess.
"""

import json
import os
import subprocess
import sys
import unittest

WIN32 = sys.platform.startswith("win")

# runs in the hardened subprocess, prints a json dict:
HARDENED = """
import json, subprocess, sys
from ctypes import byref, sizeof
from ctypes.wintypes import HANDLE
from xpra.platform.win32 import security as s
removed = s.remove_privileges()
job = s.restrict_job()
token = HANDLE()
assert s.OpenProcessToken(s.GetCurrentProcess(), s.TOKEN_QUERY, byref(token))
privileges = s.get_token_privileges(token)
remaining = [s.get_privilege_name(p.Luid) for p in privileges.Privileges]
child = subprocess.run([sys.executable, "-c", sys.argv[1]], capture_output=True, text=True, check=True)
print(json.dumps({
    "removed": removed,
    "remaining": remaining,
    "job": job,
    "child-ui-limits": int(child.stdout),
}))
"""

# prints the UI restrictions of the job this process belongs to, if any:
UI_LIMITS = """
from ctypes import WinDLL, byref, sizeof
from ctypes.wintypes import DWORD
kernel32 = WinDLL("kernel32")
limits = DWORD(0)
kernel32.QueryInformationJobObject(None, 4, byref(limits), sizeof(limits), None)
print(limits.value)
"""


def run_python(*args) -> str:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(sys.path)
    return subprocess.run([sys.executable, "-c", *args],
                          capture_output=True, text=True, check=True, env=env).stdout


@unittest.skipUnless(WIN32, "win32 only")
class Win32SecurityTest(unittest.TestCase):

    def test_harden(self):
        from xpra.platform.win32.security import KEEP_PRIVILEGES, LOGON_PRIVILEGES
        parent_limits = int(run_python(UI_LIMITS))
        result = json.loads(run_python(HARDENED, UI_LIMITS))
        keep = KEEP_PRIVILEGES
        if "SeTcbPrivilege" in result["remaining"]:
            keep |= LOGON_PRIVILEGES
        self.assertTrue(set(result["remaining"]) <= keep, f"unexpected privileges: {result['remaining']}")
        self.assertIn("SeChangeNotifyPrivilege", result["remaining"])
        self.assertFalse(set(result["removed"]) & set(result["remaining"]))
        self.assertTrue(result["job"])
        # child processes must not inherit our job restrictions:
        self.assertEqual(result["child-ui-limits"], parent_limits)

    def test_ui_limits(self):
        from xpra.platform.win32.security import JOB_UI_LIMITS
        code = "from xpra.platform.win32.security import restrict_job; assert restrict_job()\n" + UI_LIMITS
        limits = int(run_python(code))
        self.assertEqual(limits & JOB_UI_LIMITS, JOB_UI_LIMITS)

    def test_harden_process(self):
        # the whole sequence, including the opt-in policy, must not fail or crash:
        os.environ["XPRA_WIN32_DISABLE_EXTENSION_POINTS"] = "1"
        try:
            out = run_python("from xpra.platform.win32.security import harden_process; harden_process(); print('ok')")
        finally:
            os.environ.pop("XPRA_WIN32_DISABLE_EXTENSION_POINTS", None)
        self.assertEqual(out.strip(), "ok")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
