#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import unittest
import subprocess

# Imports every server module with the `xpra.client` packages made unimportable,
# as they are on a server-only install (ie: #5050).
# Modules that fail to import for any other reason (missing optional dependencies,
# other platforms) are ignored: only imports of `xpra.client` are reported.
# This runs in a subprocess, so the blocked imports cannot affect other tests.
CHECK_SCRIPT = r"""
import sys
import pkgutil
import traceback
import importlib


class BlockClient:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "xpra.client" or fullname.startswith("xpra.client."):
            raise ModuleNotFoundError(f"No module named {fullname!r}", name=fullname)
        return None


sys.meta_path.insert(0, BlockClient())

import xpra.server

modules = ["xpra.scripts.server"]
modules += [info.name for info in pkgutil.walk_packages(xpra.server.__path__, "xpra.server.", onerror=lambda name: None)]
for mod in modules:
    try:
        importlib.import_module(mod)
    except ImportError as e:
        name = e.name or ""
        if name == "xpra.client" or name.startswith("xpra.client."):
            print(f"{mod} requires {name}:")
            print("".join(traceback.format_exception(e)))
    except Exception:
        pass
"""


class NoClientImportTest(unittest.TestCase):

    def test_server_modules_without_client(self):
        env = os.environ.copy()
        # importing must not touch any display:
        for var in ("DISPLAY", "WAYLAND_DISPLAY"):
            env.pop(var, None)
        # use the same `xpra` as this test:
        env["PYTHONPATH"] = os.pathsep.join(sys.path)
        proc = subprocess.run([sys.executable, "-c", CHECK_SCRIPT], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=300)
        self.assertEqual(proc.returncode, 0, f"import check failed:\n{proc.stderr}")
        self.assertEqual(proc.stdout, "", f"server modules must not depend on `xpra.client`:\n{proc.stdout}")


if __name__ == "__main__":
    unittest.main()
