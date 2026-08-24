#!/usr/bin/env python3

import os
import unittest
from unittest.mock import call, patch

from xpra.os_util import OSX, POSIX
from xpra.util.io import pollwait
from xpra.util.env import OSEnvContext
from unit.server_test_util import ServerTestUtil


class X11WindowBindingsTest(ServerTestUtil):

    def test_window_stacking(self):
        display = self.find_free_display()
        xvfb = self.start_Xvfb(display)
        try:
            with OSEnvContext():
                os.environ["DISPLAY"] = display
                from xpra.x11.bindings.display_source import X11DisplayContext

                with X11DisplayContext(display):
                    from xpra.x11.wm import Wm

                    wm = Wm("Xpra-Test")
                    wm._windows = {1: object(), 2: object(), 3: object()}
                    wm._windows_in_order = [1, 2, 3]
                    with patch.object(Wm, "_set_window_list") as set_window_list:
                        wm._update_window_list()
                        self.assertEqual(wm._windows_stacking, [1, 2, 3])
                        set_window_list.assert_has_calls([
                            call("_NET_CLIENT_LIST", [1, 2, 3]),
                            call("_NET_CLIENT_LIST_STACKING", [1, 2, 3]),
                        ])

                        wm.update_window_stacking([3, 1, 3])
                        self.assertEqual(wm._windows_stacking, [3, 1, 2])
                        set_window_list.assert_called_with("_NET_CLIENT_LIST_STACKING", [3, 1, 2])

                        wm._windows[4] = object()
                        wm._windows_in_order.append(4)
                        wm._update_window_list()
                        self.assertEqual(wm._windows_stacking, [3, 1, 2, 4])

                        del wm._windows[1]
                        wm._windows_in_order.remove(1)
                        wm._update_window_list()
                        self.assertEqual(wm._windows_stacking, [3, 2, 4])
                        set_window_list.assert_called_with("_NET_CLIENT_LIST_STACKING", [3, 2, 4])
        finally:
            xvfb.terminate()
            self.assertIsNotNone(pollwait(xvfb, 10))

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
