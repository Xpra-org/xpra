#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch


class TestIBusStart(unittest.TestCase):

    def test_get_ibus_dirs(self):
        from xpra.x11.subsystem.keyboard import get_ibus_dirs
        with tempfile.TemporaryDirectory() as tmpdir:
            config = os.path.join(tmpdir, "config")
            cache = os.path.join(tmpdir, "cache")
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": config, "XDG_CACHE_HOME": cache}):
                dirs = get_ibus_dirs()
            self.assertEqual(dirs, (os.path.join(config, "ibus", "bus"), os.path.join(cache, "ibus")))
            for path in dirs:
                assert os.path.isdir(path)

    def test_may_start_ibus(self):
        from xpra.x11.subsystem import keyboard
        scheduler = Mock()
        with tempfile.TemporaryDirectory() as tmpdir, \
                patch.dict(os.environ, {"XPRA_SESSION_DIR": tmpdir}), \
                patch.object(keyboard, "find_libexec_command", return_value=""), \
                patch.object(keyboard, "Popen") as popen, \
                patch("xpra.util.child_reaper.get_child_reaper"):
            keyboard.may_start_ibus({}, scheduler)
        # started immediately, not from the main loop: the server may be confined by then
        popen.assert_called_once()
        scheduler.idle_add.assert_not_called()

    @staticmethod
    def make_manager(input_method="ibus"):
        from xpra.x11.subsystem import keyboard
        manager = keyboard.X11KeyboardManager.__new__(keyboard.X11KeyboardManager)
        manager.input_method = input_method
        manager.server = SimpleNamespace(get_child_env=dict)
        return manager

    def test_early_setup(self):
        from xpra.x11.subsystem import keyboard
        manager = self.make_manager()
        with patch.object(keyboard, "configure_imsettings_env", return_value="ibus"), \
                patch.object(keyboard, "IBUS", True), \
                patch.object(keyboard, "may_start_ibus") as may_start_ibus:
            manager.early_setup()
        may_start_ibus.assert_called_once_with({}, manager)

    def test_landlock_paths(self):
        from xpra.x11.subsystem import keyboard
        self.assertEqual(self.make_manager("xim").get_landlock_paths(), {})
        dirs = ("/home/user/.config/ibus/bus", "/home/user/.cache/ibus")
        with patch.object(keyboard, "get_ibus_dirs", return_value=dirs):
            paths = self.make_manager().get_landlock_paths()
        self.assertEqual(paths, {"read": (dirs[0], ), "socket": (dirs[1], )})


def main():
    from xpra.os_util import POSIX, OSX
    if POSIX and not OSX:
        unittest.main()


if __name__ == "__main__":
    main()
