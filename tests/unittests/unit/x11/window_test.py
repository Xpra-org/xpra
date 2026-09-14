#!/usr/bin/env python3

import os
import struct
import subprocess
import sys
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

    def test_window_pid(self):
        display = self.find_free_display()
        xvfb = self.start_Xvfb(display)
        try:
            with OSEnvContext():
                os.environ["DISPLAY"] = display
                from xpra.x11.bindings.core import get_root_xid
                from xpra.x11.bindings.display_source import X11DisplayContext
                from xpra.x11.bindings.window import X11WindowBindings

                with X11DisplayContext(display):
                    from xpra.x11.bindings.res import ResBindings
                    if not ResBindings().check_xres():
                        raise unittest.SkipTest("no XRes extension")
                    from xpra.x11.common import get_pid
                    x11window = X11WindowBindings()
                    window = x11window.CreateWindow(get_root_xid(), 0, 0, 32, 32)
                    try:
                        # we created this window, so it must be attributed to this process,
                        # both on the first call and via the cached bindings:
                        self.assertEqual(get_pid(window), os.getpid())
                        self.assertEqual(get_pid(window), os.getpid())
                    finally:
                        x11window.DestroyWindow(window)
        finally:
            xvfb.terminate()
            self.assertIsNotNone(pollwait(xvfb, 10))


class AttentionRequestedTest(ServerTestUtil):
    """
    `attention-requested` is a virtual property backed by the `state` property,
    so it can only be updated via `update_wm_state`.
    """

    def start_urgent_window(self, display: str) -> tuple:
        helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "urgent_window.py")
        env = self.get_default_run_env()
        env["DISPLAY"] = display
        proc = self.run_command([sys.executable, helper, display, "urgent"],
                                env=env, stdout=subprocess.PIPE)
        with proc.stdout:
            line = proc.stdout.readline()
        if not line:
            proc.terminate()
            raise unittest.SkipTest("failed to create a window on %s" % display)
        return proc, int(line.strip())

    @staticmethod
    def set_wm_hints(xid: int, flags: int) -> None:
        from xpra.x11.prop import raw_prop_set
        raw_prop_set(xid, "WM_HINTS", "WM_HINTS", 32,
                     struct.pack(b"@9l", flags, 1, 1, 0, 0, 0, 0, 0, 0))

    def test_wm_hints_urgency(self):
        InputHint = 1 << 0
        StateHint = 1 << 1
        WindowGroupHint = 1 << 6
        XUrgencyHint = 1 << 8
        DEMANDS_ATTENTION = "_NET_WM_STATE_DEMANDS_ATTENTION"
        display = self.find_free_display()
        xvfb = self.start_Xvfb(display)
        client = None
        try:
            client, xid = self.start_urgent_window(display)
            with OSEnvContext():
                os.environ["DISPLAY"] = display
                from xpra.x11.bindings.display_source import X11DisplayContext

                with X11DisplayContext(display):
                    from xpra.x11.bindings.core import get_root_xid
                    from xpra.x11.bindings.window import X11WindowBindings
                    from xpra.x11.models.window import WindowModel
                    x11window = X11WindowBindings()
                    parking = x11window.CreateWindow(get_root_xid(), 0, 0, 1, 1, OR=1)
                    # the urgency hint was set before we managed the window:
                    model = WindowModel(parking, xid, (1024, 768))
                    self.assertTrue(model.get_property("attention-requested"))
                    self.assertIn(DEMANDS_ATTENTION, model.get_property("state"))

                    notified = []
                    model.connect("notify::attention-requested",
                                  lambda *_args: notified.append(model.get_property("attention-requested")))

                    # clearing the urgency hint must clear the state and notify the clients:
                    self.set_wm_hints(xid, InputHint | StateHint)
                    model._handle_wm_hints_change()
                    self.assertFalse(model.get_property("attention-requested"))
                    self.assertNotIn(DEMANDS_ATTENTION, model.get_property("state"))
                    self.assertEqual(notified, [False])

                    # a request made through `_NET_WM_STATE` must survive
                    # an unrelated `WM_HINTS` change:
                    model.update_wm_state("attention-requested", True)
                    self.set_wm_hints(xid, InputHint | StateHint | WindowGroupHint)
                    model._handle_wm_hints_change()
                    self.assertTrue(model.get_property("attention-requested"))

                    # and the urgency hint must still be able to set it again:
                    model.update_wm_state("attention-requested", False)
                    self.set_wm_hints(xid, InputHint | StateHint | XUrgencyHint)
                    model._handle_wm_hints_change()
                    self.assertTrue(model.get_property("attention-requested"))
        finally:
            if client:
                client.terminate()
            xvfb.terminate()
            self.assertIsNotNone(pollwait(xvfb, 10))


def main():
    if POSIX and not OSX:
        unittest.main()


if __name__ == "__main__":
    main()
