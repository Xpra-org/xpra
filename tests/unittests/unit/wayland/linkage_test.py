#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import importlib.util
import subprocess
import sys
import unittest


WAYLAND_MODULES = (
    "xpra.wayland.events",
    "xpra.wayland.display",
)


class WaylandLinkageTest(unittest.TestCase):

    def test_isolated_imports(self):
        available = tuple(module for module in WAYLAND_MODULES if importlib.util.find_spec(module))
        if not available:
            self.skipTest("Wayland server modules are not built")
        self.assertEqual(available, WAYLAND_MODULES)
        for module in WAYLAND_MODULES:
            with self.subTest(module=module):
                proc = subprocess.run(
                    (sys.executable, "-c", f"import {module}"),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
