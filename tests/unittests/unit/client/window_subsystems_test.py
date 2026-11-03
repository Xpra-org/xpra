#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Every window class declares the client subsystems it looks up in `SUBSYSTEMS`.
The sources are parsed rather than imported, so the classes of other platforms are checked too.
"""

import os
import ast
import glob
import unittest

import xpra

XPRA_DIR = os.path.dirname(xpra.__file__)

# the modules of the window classes, and of the classes they use with the window's `get_subsystem`:
WINDOW_MODULES = (
    "client/gtk3/window/*.py",
    "client/gtk3/opengl/*.py",
    "client/gui/widget_base.py",
    "client/gui/window_base.py",
    "client/gui/client_tray.py",
    "client/win32/window.py",
    "client/win32/opengl/window.py",
    "client/terminal/window.py",
    "platform/posix/xi2.py",
)


def window_module_paths() -> list[str]:
    paths = []
    for pattern in WINDOW_MODULES:
        paths += sorted(glob.glob(os.path.join(XPRA_DIR, pattern)))
    return paths


def subsystem_lookups(node: ast.AST) -> tuple[set[str], list[int]]:
    """ the subsystem names looked up with `get_subsystem("name")`, and the lines of any other lookups """
    names: set[str] = set()
    other: list[int] = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get_subsystem":
            if n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                names.add(n.args[0].value)
            else:
                other.append(n.lineno)
    return names, other


def declared_subsystems(cls: ast.ClassDef) -> tuple[str, ...] | None:
    for n in cls.body:
        target = n.target if isinstance(n, ast.AnnAssign) else (n.targets[0] if isinstance(n, ast.Assign) else None)
        if isinstance(target, ast.Name) and target.id == "SUBSYSTEMS":
            return ast.literal_eval(n.value)
    return None


def subsystem_prefixes() -> set[str]:
    """ the names the client subsystems are registered with (their `PREFIX`) """
    prefixes = set()
    for path in glob.glob(os.path.join(XPRA_DIR, "client", "**", "*.py"), recursive=True):
        with open(path, encoding="utf8") as f:
            tree = ast.parse(f.read())
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            for n in cls.body:
                target = n.target if isinstance(n, ast.AnnAssign) else (n.targets[0] if isinstance(n, ast.Assign) else None)
                if isinstance(target, ast.Name) and target.id == "PREFIX" and isinstance(n.value, ast.Constant):
                    prefixes.add(n.value.value)
    return prefixes


class WindowSubsystemsTest(unittest.TestCase):

    def window_classes(self):
        paths = window_module_paths()
        self.assertTrue(paths)
        for path in paths:
            with open(path, encoding="utf8") as f:
                tree = ast.parse(f.read())
            for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
                yield os.path.relpath(path, XPRA_DIR), cls

    def test_declarations_match_lookups(self) -> None:
        checked = 0
        for path, cls in self.window_classes():
            with self.subTest(path=path, cls=cls.name):
                used, other = subsystem_lookups(cls)
                self.assertEqual(other, [], "the subsystem names must be literals so they can be checked")
                declared = declared_subsystems(cls)
                if not used:
                    self.assertIsNone(declared, "declares subsystems it does not look up")
                    continue
                self.assertIsNotNone(declared, f"looks up {sorted(used)} without declaring them in 'SUBSYSTEMS'")
                self.assertEqual(set(declared), used)
                self.assertEqual(list(declared), sorted(declared), "keep 'SUBSYSTEMS' sorted")
                checked += 1
        # make sure we did find the classes:
        self.assertGreater(checked, 10)

    def test_names_are_subsystems(self) -> None:
        prefixes = subsystem_prefixes()
        self.assertIn("window", prefixes)
        for path, cls in self.window_classes():
            for name in declared_subsystems(cls) or ():
                with self.subTest(path=path, cls=cls.name, name=name):
                    self.assertIn(name, prefixes)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
