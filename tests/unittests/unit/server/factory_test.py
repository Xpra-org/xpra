#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import builtins
import sys
import unittest
from types import ModuleType
from unittest.mock import Mock, patch

from xpra.server import factory, features
from xpra.server.base import ServerBase


class ServerFactoryTest(unittest.TestCase):

    def setUp(self):
        disabled = {name: False for name, value in vars(features).items() if isinstance(value, bool)}
        flags = patch.dict(vars(features), disabled)
        flags.start()
        self.addCleanup(flags.stop)
        platform = patch.object(factory, "POSIX", False)
        platform.start()
        self.addCleanup(platform.stop)
        self.server = ServerBase.__new__(ServerBase)
        self.selectors = {}
        for name in ("gtk", "display", "window", "keyboard", "pointer", "cursor", "clipboard", "bell"):
            cls = type(f"Backend_{name}", (), {"PREFIX": name})
            selector = Mock(return_value=cls)
            setattr(self.server, f"get_{name}_subsystem_class", selector)
            self.selectors[name] = selector

    def test_disabled_backends_are_not_imported(self):
        original_import = builtins.__import__

        def without_backends(name, *args, **kwargs):
            for backend in ("xpra.x11", "xpra.wayland", "xpra.gtk"):
                if name == backend or name.startswith(backend + "."):
                    raise AssertionError(f"disabled backend imported: {name}")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=without_backends):
            classes = self.server.get_subsystem_classes()
        self.assertEqual(tuple(cls.PREFIX for cls in classes), ("sharing", "encryption", "client-session", "setting", "shutdown"))
        for selector in self.selectors.values():
            selector.assert_not_called()

    def test_backend_selectors_and_dependency_order(self):
        enabled = {name: True for name in (*self.selectors, "dbus", "command")}
        with patch.dict(vars(features), enabled):
            classes = self.server.get_subsystem_classes()
        prefixes = tuple(cls.PREFIX for cls in classes)
        for selector in self.selectors.values():
            selector.assert_called_once_with()
            self.assertIn(selector.return_value, classes)
        self.assertLess(prefixes.index("gtk"), prefixes.index("dbus"))
        self.assertLess(prefixes.index("dbus"), prefixes.index("sharing"))
        for name in ("display", "window", "keyboard", "pointer"):
            self.assertLess(prefixes.index("sharing"), prefixes.index(name))
            self.assertLess(prefixes.index(name), prefixes.index("command"))
        self.assertLess(prefixes.index("command"), prefixes.index("client-session"))
        self.assertLess(prefixes.index("client-session"), prefixes.index("cursor"))

    def test_x11_init_only_without_gtk(self):
        x11init = ModuleType("xpra.x11.subsystem.x11init")
        x11init.X11Init = type("X11Init", (), {"PREFIX": "x11-init"})
        self.selectors["gtk"].return_value = None
        with patch.dict(sys.modules, {x11init.__name__: x11init}), patch.object(features, "x11", True):
            for gtk in (False, True):
                with self.subTest(gtk=gtk), patch.object(features, "gtk", gtk):
                    classes = self.server.get_subsystem_classes()
                    self.assertEqual(x11init.X11Init in classes, not gtk)
                    self.assertNotIn(None, classes)

    def test_drm_requires_posix_and_full_info(self):
        for posix, full_info, expected in ((False, 1, False), (True, 0, False), (True, 1, True)):
            with self.subTest(posix=posix, full_info=full_info), \
                 patch.object(factory, "POSIX", posix), patch.object(factory, "FULL_INFO", full_info):
                prefixes = tuple(cls.PREFIX for cls in self.server.get_subsystem_classes())
            self.assertEqual("drm" in prefixes, expected)


if __name__ == "__main__":
    unittest.main()
