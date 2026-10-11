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
import json
from ctypes import byref
from ctypes.wintypes import HANDLE
from xpra.platform.win32 import security as s
removed = s.remove_privileges()
token = HANDLE()
assert s.OpenProcessToken(s.GetCurrentProcess(), s.TOKEN_QUERY, byref(token))
privileges = s.get_token_privileges(token)
remaining = [s.get_privilege_name(p.Luid) for p in privileges.Privileges]
print(json.dumps({
    "removed": removed,
    "remaining": remaining,
}))
"""

# reads the clipboard text, without modifying the clipboard:
READ_CLIPBOARD = """
import sys
from ctypes import WinDLL, c_void_p, c_wchar_p, cast
from ctypes.wintypes import BOOL, HANDLE, HWND, UINT
if sys.argv[1:] == ["harden"]:
    from xpra.platform.win32.security import harden_process
    harden_process()
user32 = WinDLL("user32")
kernel32 = WinDLL("kernel32")
user32.OpenClipboard.argtypes = [HWND]
user32.OpenClipboard.restype = BOOL
user32.GetClipboardData.argtypes = [UINT]
user32.GetClipboardData.restype = HANDLE
kernel32.GlobalLock.argtypes = [HANDLE]
kernel32.GlobalLock.restype = c_void_p
kernel32.GlobalUnlock.argtypes = [HANDLE]
text = None
if user32.OpenClipboard(None):
    try:
        data = user32.GetClipboardData(13)  # CF_UNICODETEXT
        if data:
            text = cast(kernel32.GlobalLock(data), c_wchar_p).value
            kernel32.GlobalUnlock(data)
    finally:
        user32.CloseClipboard()
print(len(text) if text is not None else -1)
"""


def run_python(*args) -> str:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(sys.path)
    return subprocess.run([sys.executable, "-c", *args],
                          capture_output=True, text=True, check=True, env=env).stdout


@unittest.skipUnless(WIN32, "win32 only")
class Win32SecurityTest(unittest.TestCase):

    def test_remove_privileges(self):
        from xpra.platform.win32.security import KEEP_PRIVILEGES, LOGON_PRIVILEGES
        result = json.loads(run_python(HARDENED))
        keep = KEEP_PRIVILEGES
        if "SeTcbPrivilege" in result["remaining"]:
            keep |= LOGON_PRIVILEGES
        self.assertTrue(set(result["remaining"]) <= keep, f"unexpected privileges: {result['remaining']}")
        self.assertIn("SeChangeNotifyPrivilege", result["remaining"])
        self.assertFalse(set(result["removed"]) & set(result["remaining"]))

    def test_clipboard_access(self):
        # the clipboard data owned by other processes must remain readable:
        # (a job object with UI restrictions breaks this)
        self.assertEqual(run_python(READ_CLIPBOARD, "harden"), run_python(READ_CLIPBOARD))

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
