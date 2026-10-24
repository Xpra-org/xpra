#!/usr/bin/env python3

import os
import struct
import subprocess
import sys
import unittest
from collections import deque
from contextlib import ExitStack
from unittest.mock import Mock, call, patch

from xpra.os_util import OSX, POSIX
from xpra.util.io import pollwait
from xpra.util.env import OSEnvContext
from xpra.util.objects import AdHocStruct
from xpra.net.common import Packet
from unit.server_test_util import ServerTestUtil


class FocusStub:
    """ the minimum amount of server state needed to focus and lose windows """

    def __init__(self, wm=None, windows: dict | None = None):
        self.last_raised = 0
        self._has_focus = 0
        self._focus_history = deque(maxlen=10)
        self._wm = wm
        self.windows = windows or {}
        self.window_movers = {}

    def get_window(self, wid: int):
        return self.windows.get(wid)

    @staticmethod
    def get_subsystem(_name: str):
        return None

    def focus(self, wid: int) -> None:
        """ replay a `window-focus` packet, without a server """
        from xpra.x11.subsystem.window import SeamlessWindowServer
        SeamlessWindowServer._focus(self, None, wid, None)

    def lose_window(self, window) -> None:
        """ what happens when a window goes away, without a server """
        from xpra.x11.subsystem.window import SeamlessWindowServer
        self.restore_active_window = lambda w: SeamlessWindowServer.restore_active_window(self, w)
        self.reset_focus = lambda: self.focus(0)
        self.cancel_configure_damage = lambda wid: None
        self.repaint_root_overlay = lambda: None
        self._exit_with_windows = False
        SeamlessWindowServer._lost_window(self, window)

    def _remove_window(self, window) -> int:
        wid = self.get_wid(window)
        self.windows.pop(wid)
        return wid

    def get_wid(self, window) -> int:
        return next(wid for wid, w in self.windows.items() if w is window)


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

    def test_dismiss_grabbed_popup(self):
        from xpra.x11.subsystem.display import x11_ungrab
        from xpra.x11.subsystem.window import SeamlessWindowServer
        from xpra.x11.bindings.window import X11WindowBindings

        helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "grabbed_popup.py")
        command = [sys.executable, helper, self.display]
        env = self.get_default_run_env()
        proc = self.run_command(command, env=env, stdout=subprocess.PIPE)
        self.addCleanup(proc.terminate)
        with proc.stdout:
            line = proc.stdout.readline()
        xid, pointer, keyboard = map(int, line.split())
        self.assertEqual((pointer, keyboard), (0, 0))

        def probe() -> tuple[int, ...]:
            output = subprocess.check_output(command + ["probe"], env=env, timeout=10)
            return tuple(map(int, output.split()))[1:]

        # A second X11 client cannot grab either device, even after Xpra's ungrab.
        self.assertEqual(probe(), (1, 1))  # AlreadyGrabbed
        x11_ungrab()
        self.assertEqual(probe(), (1, 1))
        window = Mock()
        window.is_OR.return_value = True
        window.is_tray.return_value = False
        window.get_property.return_value = xid
        server = AdHocStruct()
        server.is_readonly = lambda _proto: False
        server.get_server_source = lambda _proto: AdHocStruct()
        server.get_window = lambda wid: window if wid == 1 else None
        SeamlessWindowServer._process_dismiss(server, object(), Packet("window-dismiss", 1))
        self.assertFalse(X11WindowBindings().is_mapped(xid))
        # The application is still running and has never called ungrab.
        self.assertIsNone(proc.poll())
        self.assertEqual(probe(), (0, 0))

    def test_managed_configure_request_coordinates(self):
        """Use real X11 windows to keep root geometry off the reparented child."""
        from types import SimpleNamespace
        from xpra.x11.models import window
        from xpra.x11.bindings.core import X11CoreBindings
        from xpra.x11.bindings.window import X11WindowBindings

        model = self.manage_window(self.start_window())
        x11 = X11WindowBindings()
        expected = [200, 300, 413, 229]
        for mask, values in (
                (window.CONFIGURE_GEOMETRY_MASK, (200, 300, 413, 229)),
                (window.CWX, (240, 0, 1, 1)),
                (window.CWY, (0, 350, 1, 1)),
                (window.CWWidth, (0, 0, 500, 1)),
                (window.CWHeight, (0, 0, 1, 270)),
                (window.CWX | window.CWY, (0, 0, 1, 1)),
                (window.CONFIGURE_GEOMETRY_MASK, (250, 200, 420, 240)),
                (window.CWX, (-30, 0, 1, 1)),
        ):
            with self.subTest(mask=mask, request=values):
                for index, flag in enumerate((window.CWX, window.CWY, window.CWWidth, window.CWHeight)):
                    if mask & flag:
                        expected[index] = values[index]
                event = SimpleNamespace(value_mask=mask, x=values[0], y=values[1], width=values[2], height=values[3])
                model.do_x11_child_configure_request_event(event)
                X11CoreBindings().XSync()
                self.assertEqual(model.get_property("geometry"), tuple(expected))
                self.assertEqual(x11.getGeometry(model.corral_xid)[:4], tuple(expected))
                self.assertEqual(x11.getGeometry(model.xid)[:4], (0, 0, *expected[2:]))
                self.assertEqual(x11.get_absolute_position(model.xid), tuple(expected[:2]))

    def test_dismiss_popup_guards(self):
        from xpra.x11.subsystem.window import SeamlessWindowServer

        for readonly, source, popup, tray, hidden, exists in (
                (True, True, True, False, False, True),
                (False, False, True, False, False, True),
                (False, True, False, False, False, True),
                (False, True, True, True, False, True),
                (False, True, True, False, True, True),
                (False, True, True, False, False, False),
        ):
            with self.subTest(readonly=readonly, source=source, popup=popup, tray=tray, hidden=hidden, exists=exists):
                window = Mock()
                window.is_OR.return_value = popup
                window.is_tray.return_value = tray
                ss = Mock()
                ss.is_window_hidden.return_value = hidden
                server = AdHocStruct()
                server.is_readonly = lambda _proto: readonly
                server.get_server_source = lambda _proto: ss if source else None
                server.get_window = lambda _wid: window if exists else None
                with patch("xpra.x11.subsystem.window.X11WindowBindings") as bindings:
                    SeamlessWindowServer._process_dismiss(server, object(), Packet("window-dismiss", 1))
                    bindings.assert_not_called()

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

    def test_x11_property_denylist(self):
        from xpra.x11.error import xsync
        from xpra.x11.prop import prop_set
        model = self.manage_window(self.start_window())
        changed = []
        model.connect("x11-property-changed", lambda _model, event: changed.append(event[0]))
        for name in ("_MY_APP_PROPERTY", "_KDE_NET_WM_BLUR_BEHIND_REGION", "_NET_STARTUP_ID", "WM_LOCALE_NAME"):
            with xsync:
                prop_set(model.xid, name, "latin1", "value")
            model._handle_property_change(name)
        self.assertEqual(changed, ["_MY_APP_PROPERTY"])

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

    def test_focus_raises_window(self):
        from xpra.x11.bindings.core import get_root_xid
        from xpra.x11.bindings.window import X11WindowBindings
        from xpra.x11.error import xsync

        first = self.manage_window(self.start_window())
        second = self.manage_window(self.start_window())
        server = FocusStub(windows={1: first, 2: second})
        bindings = X11WindowBindings()
        root = get_root_xid()

        for wid, focused, covering in ((1, first, second), (2, second, first)):
            with self.subTest(wid=wid):
                server.focus(wid)
                self.assertEqual(bindings.get_children(root)[-1], focused.corral_xid)
                with xsync:
                    covering.raise_window()
                self.assertEqual(bindings.XGetInputFocus()[0], focused.xid)
                self.assertEqual(bindings.get_children(root)[-1], covering.corral_xid)
                # The client can send the same focus again after another window
                # has covered it on the server, without changing the input focus.
                history = tuple(server._focus_history)
                server.focus(wid)
                self.assertEqual(bindings.get_children(root)[-1], focused.corral_xid)
                self.assertEqual(tuple(server._focus_history), history)

    def test_pointer_raises_stationary_window(self):
        from xpra.x11.bindings.core import get_root_xid
        from xpra.x11.bindings.window import X11WindowBindings
        from xpra.x11.server.pointer import X11SeamlessPointerManager
        from xpra.x11.server.xtest_pointer import XTestPointerDevice
        from xpra.x11.subsystem.window import SeamlessWindowServer

        first = self.manage_window(self.start_window())
        second = self.manage_window(self.start_window())
        source = AdHocStruct()
        source.get_monitor_position = lambda *_args: (400, 500)
        server = AdHocStruct()
        server.subsystems = {}
        server.get_server_source = lambda _proto: source
        server.get_sources_by_type = lambda *_args: ()
        windows = SeamlessWindowServer(server)
        windows._id_to_window = {1: first, 2: second}
        server.subsystems["window"] = windows
        pointer = X11SeamlessPointerManager(server)
        pointer.pointer_device = XTestPointerDevice()
        pointer.pointer_device.move_pointer(20, 20, {})
        bindings = X11WindowBindings()
        root = get_root_xid()
        self.assertEqual(bindings.get_children(root)[-1], second.corral_xid)

        # Wayland client windows can have the same server coordinates: changing
        # the target window must raise it even when the pointer does not move.
        props = {"window-position": (20, 20), "monitor": {"index": 0, "position": (400, 500)}}
        pointer.process_mouse_common(object(), 0, 1, (400, 500), props)
        self.assertEqual(bindings.get_children(root)[-1], first.corral_xid)
        self.assertEqual(pointer.pointer_device.get_position(), (20, 20))
        for pressed in (True, False):
            pointer.process_pointer_button(object(), 0, 2, 1, pressed, (400, 500), props)
            self.assertEqual(bindings.get_children(root)[-1], second.corral_xid)
            self.assertEqual(pointer.pointer_device.get_position(), (20, 20))

    def test_lost_active_window(self):
        """
        A transient window can become `_NET_ACTIVE_WINDOW` without taking the input focus
        (ie: by sending a `_NET_ACTIVE_WINDOW` client message),
        the property must not be left pointing at it when it goes away.
        """
        from xpra.x11.bindings.window import X11WindowBindings
        from xpra.x11.xroot_props import root_get, root_set
        X11Window = X11WindowBindings()
        parent = self.manage_window(self.start_window())
        transient = self.manage_window(self.start_window())
        other = self.manage_window(self.start_window())
        server = FocusStub(windows={1: parent, 2: transient, 3: other})
        server.focus(1)
        # what the `_NET_ACTIVE_WINDOW` client message handler does:
        transient.set_active()
        self.assertEqual(X11Window.XGetInputFocus()[0], parent.xid)
        server.lose_window(transient)
        self.assertEqual(root_get("_NET_ACTIVE_WINDOW", "u32"), parent.xid)
        self.assertEqual(server._has_focus, 1)

        # losing a window which is not the active one leaves the property alone:
        server.lose_window(other)
        self.assertEqual(root_get("_NET_ACTIVE_WINDOW", "u32"), parent.xid)

        # and without any focused window, the property is cleared:
        server._has_focus = 0
        root_set("_NET_ACTIVE_WINDOW", "u32", parent.xid)
        server.lose_window(parent)
        self.assertEqual(root_get("_NET_ACTIVE_WINDOW", "u32"), 0)


def main():
    if POSIX and not OSX:
        unittest.main()


if __name__ == "__main__":
    main()
