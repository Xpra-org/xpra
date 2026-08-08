#!/usr/bin/env python3

import os
import unittest

from xpra.os_util import OSX, POSIX
from xpra.util.io import pollwait
from xpra.util.env import OSEnvContext
from unit.server_test_util import ServerTestUtil


class X11WindowBindingsTest(ServerTestUtil):

    def test_set_input_focus_revert_to(self):
        display = self.find_free_display()
        xvfb = self.start_Xvfb(display)
        try:
            with OSEnvContext():
                os.environ["DISPLAY"] = display
                from xpra.x11.bindings.core import constants, get_root_xid
                from xpra.x11.bindings.display_source import X11DisplayContext
                from xpra.x11.bindings.window import X11WindowBindings

                with X11DisplayContext(display):
                    x11window = X11WindowBindings()
                    root = get_root_xid()
                    window = x11window.CreateWindow(root, 0, 0, 32, 32)
                    try:
                        x11window.MapWindow(window)
                        self.assertNotEqual(x11window.get_map_state(window), constants["IsUnmapped"])
                        for name in ("RevertToParent", "RevertToPointerRoot", "RevertToNone"):
                            revert_to = constants[name]
                            x11window.XSetInputFocus(window, revert_to=revert_to)
                            focus, actual_revert_to = x11window.XGetInputFocus()
                            self.assertEqual(focus, window)
                            self.assertEqual(actual_revert_to, revert_to)
                    finally:
                        x11window.XSetInputFocus(root)
                        x11window.DestroyWindow(window)
        finally:
            xvfb.terminate()
            self.assertIsNotNone(pollwait(xvfb, 10))


def main():
    if POSIX and not OSX:
        unittest.main()


if __name__ == "__main__":
    main()
