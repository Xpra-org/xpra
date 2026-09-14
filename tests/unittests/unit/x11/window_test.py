#!/usr/bin/env python3

import os
import struct
import subprocess
import sys
import unittest
from collections import deque
from contextlib import ExitStack
from unittest.mock import call, patch

from xpra.os_util import OSX, POSIX
from xpra.util.io import pollwait
from xpra.util.env import OSEnvContext
from unit.server_test_util import ServerTestUtil


class FocusStub:
    """ the minimum amount of server state that `SeamlessWindowServer._focus` needs """

    def __init__(self, wm=None, windows: dict | None = None):
        self.last_raised = 0
        self._has_focus = 0
        self._focus_history = deque(maxlen=10)
        self._wm = wm
        self.windows = windows or {}

    def get_window(self, wid: int):
        return self.windows.get(wid)

    @staticmethod
    def get_subsystem(_name: str):
        return None

    def focus(self, wid: int) -> None:
        """ replay a `window-focus` packet, without a server """
        from xpra.x11.subsystem.window import SeamlessWindowServer
        SeamlessWindowServer._focus(self, None, wid, None)


class X11WindowTest(ServerTestUtil):
    """
    All these tests share a single display:
    `xpra.x11.wm` and the window models capture the X11 bindings in module globals
    when they are first imported, and those stay bound to whichever display
    was current at the time - using another one later crashes in `libX11`.
    """

    @classmethod
    def setUpClass(cls):
        ServerTestUtil.setUpClass()
        cls.stack = ExitStack()
        cls.display = cls.find_free_display()
        cls.xvfb = cls.start_Xvfb(cls.display)
        cls.stack.enter_context(OSEnvContext())
        os.environ["DISPLAY"] = cls.display
        from xpra.x11.bindings.display_source import X11DisplayContext
        cls.stack.enter_context(X11DisplayContext(cls.display))
        # this installs the X11 error handlers, so that `xsync` and friends
        # actually trap the errors instead of letting Xlib abort the process:
        from xpra.x11.bindings.loop import EventLoop
        cls.event_loop = EventLoop()

    def setUp(self):
        super().setUp()
        # `ProcessTestUtil.setUp` resets the whole environment:
        os.environ["DISPLAY"] = self.display

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()
        cls.xvfb.terminate()
        pollwait(cls.xvfb, 10)
        ServerTestUtil.tearDownClass()

    def start_window(self, *args) -> int:
        """ map a window from another process and return its xid:
            a window manager is not allowed to add its own windows to the X11 save-set,
            so anything we want to manage has to belong to a different X11 client """
        helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "urgent_window.py")
        env = self.get_default_run_env()
        env["DISPLAY"] = self.display
        proc = self.run_command([sys.executable, helper, self.display] + list(args),
                                env=env, stdout=subprocess.PIPE)
        self.addCleanup(proc.terminate)
        with proc.stdout:
            line = proc.stdout.readline()
        if not line:
            raise unittest.SkipTest("failed to create a window on %s" % self.display)
        return int(line.strip())

    def manage_window(self, xid: int):
        """ manage a window the way `Wm` does, and unmanage it when the test ends """
        from xpra.x11.bindings.core import get_root_xid
        from xpra.x11.models.window import WindowModel
        # the window manager parks the corral windows on the root window:
        model = WindowModel(get_root_xid(), xid, (1024, 768))
        self.addCleanup(model.unmanage, True)
        # mapped, so that it can be given the X11 input focus:
        model.show()
        return model

    def test_window_stacking(self):
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

    def test_set_input_focus_revert_to(self):
        from xpra.x11.bindings.core import constants, get_root_xid
        from xpra.x11.bindings.window import X11WindowBindings

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

    def test_window_pid(self):
        from xpra.x11.bindings.core import get_root_xid
        from xpra.x11.bindings.res import ResBindings
        from xpra.x11.bindings.window import X11WindowBindings

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

    @staticmethod
    def set_wm_hints(xid: int, flags: int) -> None:
        from xpra.x11.prop import raw_prop_set
        raw_prop_set(xid, "WM_HINTS", "WM_HINTS", 32,
                     struct.pack(b"@9l", flags, 1, 1, 0, 0, 0, 0, 0, 0))

    def test_wm_hints_urgency(self):
        """
        `attention-requested` is a virtual property backed by the `state` property,
        so it can only be updated via `update_wm_state`.
        """
        InputHint = 1 << 0
        StateHint = 1 << 1
        WindowGroupHint = 1 << 6
        XUrgencyHint = 1 << 8
        DEMANDS_ATTENTION = "_NET_WM_STATE_DEMANDS_ATTENTION"
        # the urgency hint is set before we manage the window:
        xid = self.start_window("urgent")
        model = self.manage_window(xid)
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

        # EWMH: giving the window focus clears the request
        FocusStub(windows={1: model}).focus(1)
        self.assertFalse(model.get_property("attention-requested"))
        self.assertNotIn(DEMANDS_ATTENTION, model.get_property("state"))

    def test_focus_sink(self):
        """
        X11 has no state which means "no window has the focus":
        `None` discards keystrokes silently and `PointerRoot` is focus-follows-mouse,
        so the window manager parks the input focus on a window of its own instead.
        """
        # `PointerRoot` from `X.h`, it has no binding of its own:
        PointerRoot = 1
        FOCUSED = "_NET_WM_STATE_FOCUSED"
        from xpra.x11.bindings.core import constants, get_root_xid
        from xpra.x11.bindings.window import X11WindowBindings
        from xpra.x11.xroot_props import root_get
        from xpra.x11.wm import Wm

        X11Window = X11WindowBindings()
        rxid = get_root_xid()
        wm = Wm("Xpra-Test")
        wm._focus_window = wm._setup_focus_window()
        self.addCleanup(wm.cleanup)
        sink = wm._focus_window
        self.assertTrue(sink)
        # only viewable windows can be given the input focus:
        self.assertTrue(X11Window.is_mapped(sink))
        # and it must not be picked up as a client window:
        self.assertTrue(X11Window.is_override_redirect(sink))

        model = self.manage_window(self.start_window())
        server = FocusStub(wm, {1: model})

        server.focus(1)
        self.assertEqual(X11Window.XGetInputFocus()[0], model.xid)
        self.assertIn(FOCUSED, model.get_property("state"))
        self.assertEqual(root_get("_NET_ACTIVE_WINDOW", "u32"), model.xid)

        # losing the focus must take it away from the client window,
        # otherwise it would keep receiving all the key events we inject:
        server.focus(0)
        self.assertEqual(X11Window.XGetInputFocus()[0], sink)
        self.assertNotIn(FOCUSED, model.get_property("state"))
        self.assertEqual(root_get("_NET_ACTIVE_WINDOW", "u32"), 0)

        # focus falling back to the root window (ie: a client crashed)
        # must be given back to the sink:
        X11Window.XSetInputFocus(PointerRoot)
        self.assertEqual(X11Window.XGetInputFocus()[0], PointerRoot)

        class FocusInEvent:
            window = rxid
            detail = constants["NotifyPointerRoot"]

        wm.do_x11_focus_in_event(FocusInEvent())
        self.assertEqual(X11Window.XGetInputFocus()[0], sink)

        # and the sink goes away with the window manager:
        wm.cleanup()
        self.assertFalse(wm.get_focus_window())


def main():
    if POSIX and not OSX:
        unittest.main()


if __name__ == "__main__":
    main()
