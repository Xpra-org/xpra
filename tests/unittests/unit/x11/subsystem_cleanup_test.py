#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.os_util import POSIX, OSX


def no_display():
    raise RuntimeError("X11 display is not set")


@unittest.skipUnless(POSIX and not OSX, "X11 subsystems")
class TestCleanupWithoutDisplay(unittest.TestCase):
    """
    When the virtual display fails to start, the server is cleaned up without ever being set up:
    the subsystems must not try to talk to an X11 display which does not exist.
    """

    def check_cleanup(self, module_name: str, class_name: str) -> None:
        import importlib
        try:
            module = importlib.import_module(module_name)
        except ImportError as e:
            self.skipTest(f"{module_name} is not available: {e}")
        cls = getattr(module, class_name)
        with patch.object(module, "get_root_xid", side_effect=no_display), \
                patch.object(module, "remove_event_receiver") as remove:
            # never set up:
            subsystem = cls(None)
            subsystem.cleanup()
            remove.assert_not_called()
            # set up, so the receiver is removed, but only once:
            subsystem.root_event_xid = 5
            subsystem.cleanup()
            subsystem.cleanup()
            remove.assert_called_once_with(5, subsystem)

    def test_cursor(self):
        self.check_cleanup("xpra.x11.subsystem.cursor", "XCursorServer")

    def test_bell(self):
        self.check_cleanup("xpra.x11.subsystem.bell", "X11BellServer")

    def test_bell_catchall(self):
        try:
            from xpra.x11.subsystem import bell
        except ImportError as e:
            self.skipTest(f"bell subsystem is not available: {e}")
        with patch.object(bell, "remove_catchall_receiver") as remove:
            subsystem = bell.X11BellServer(None)
            subsystem.cleanup()
            remove.assert_not_called()
            subsystem.receiving = True
            subsystem.cleanup()
            subsystem.cleanup()
            remove.assert_called_once_with("x11-xkb-event", subsystem)

    def test_window(self):
        self.check_cleanup("xpra.x11.subsystem.window", "SeamlessWindowServer")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
