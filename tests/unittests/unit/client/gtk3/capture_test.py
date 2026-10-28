#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from xpra.os_util import gi_import
from xpra.client.gtk3.window.capture import CaptureWindow, accumulate

Gdk = gi_import("Gdk")

# a 1920x1080 remote desktop, shown at a tenth of its size,
# at `ORIGIN` on a 1280x800 local monitor:
SCALE = 0.1
SIZE = (192, 108)
ORIGIN = (1000, 500)
MONITOR = SimpleNamespace(x=0, y=0, width=1280, height=800)
# we warp to the centre of the monitor, in root coordinates:
CENTER = (640, 400)


class FakePointerBase:
    """ records the calls that `CaptureWindow` passes on to `PointerWindow` and `GrabWindow` """

    def __init__(self):
        self.forwarded: list[tuple] = []

    def _do_motion_notify_event(self, event) -> None:
        self.forwarded.append(("motion", event.x, event.y))

    def get_pointer_data(self, event) -> tuple[int, int, int, int]:
        return round(event.x / SCALE), round(event.y / SCALE), round(event.x / SCALE), round(event.y / SCALE)

    def _button_action(self, button: int, event, depressed: bool, props=None) -> None:
        self.forwarded.append(("button", button, depressed))

    def on_leave_notify_event(self, window, event) -> None:
        self.forwarded.append(("leave", ))

    def grab_broken(self, win, event) -> None:
        self.forwarded.append(("grab-broken", ))


class CaptureTestWindow(CaptureWindow, FakePointerBase):
    """ just enough of a client window to exercise input capture """

    def __init__(self, server_mode="shadow", input_capture=True):
        FakePointerBase.__init__(self)
        self._xscale = self._yscale = SCALE
        self._size = SIZE
        self._pos = (0, 0)
        self._override_redirect = False
        self.wid = 1
        self.button_pressed: dict[int, int] = {}
        self.overlay = ()
        self.gdk_window = MagicMock()
        self.gdk_window.get_origin.return_value = (True, *ORIGIN)
        gdk_display = self.gdk_window.get_display.return_value
        gdk_display.get_monitor_at_window.return_value.get_geometry.return_value = MONITOR
        self.seat = gdk_display.get_default_seat.return_value
        self.seat.grab.return_value = Gdk.GrabStatus.SUCCESS
        self.subsystems = {
            "pointer": SimpleNamespace(input_capture=input_capture, send_mouse_position=MagicMock(),
                                       send_button=MagicMock()),
            "keyboard": SimpleNamespace(grabbed=False, mask_to_names=lambda _state: [],
                                        helper=SimpleNamespace(key_shortcuts={
                                            "Escape": [(["mod1", "shift"], "toggle_input_capture", [])],
                                        })),
            "remote-info": SimpleNamespace(_remote_server_mode=server_mode),
        }
        self._client = SimpleNamespace(readonly=False, server_readonly=False,
                                       get_subsystem=self.subsystems.get)
        self.init_window(None, None, None)

    def get_subsystem(self, name: str):
        return self.subsystems.get(name)

    def get_window(self):
        return self.gdk_window

    def cp(self, x, y) -> tuple[int, int]:
        return round(x / self._xscale), round(y / self._yscale)

    def sp(self, x, y) -> tuple[int, int]:
        return round(x * self._xscale), round(y * self._yscale)

    @staticmethod
    def get_capture_cursor(display):
        return None

    def show_pointer_overlay(self, pos=()) -> None:
        self.overlay = pos

    def motion(self, x_root: float, y_root: float) -> None:
        self._do_motion_notify_event(event(x_root - ORIGIN[0], y_root - ORIGIN[1]))

    def sent_positions(self) -> list[tuple[int, ...]]:
        send = self.subsystems["pointer"].send_mouse_position
        return [call.args[2] for call in send.call_args_list]


def event(x: float = 0, y: float = 0) -> SimpleNamespace:
    return SimpleNamespace(x=x, y=y, x_root=ORIGIN[0] + x, y_root=ORIGIN[1] + y, state=0)


class CaptureWindowTest(unittest.TestCase):

    def test_accumulate(self) -> None:
        self.assertEqual(accumulate((100, 100), (5, -3), (1920, 1080), 1.0), (105, 97))
        self.assertEqual(accumulate((100, 100), (5, -3), (1920, 1080), 2.0), (110, 94))
        # clamped to the remote window:
        self.assertEqual(accumulate((10, 1070), (-50, 50), (1920, 1080), 1.0), (0, 1079))

    def test_click_starts_capture(self) -> None:
        window = CaptureTestWindow()
        window._button_action(1, event(50, 20), True)
        self.assertTrue(window.input_captured)
        self.assertTrue(window.subsystems["keyboard"].grabbed)
        # the virtual pointer starts where we clicked, in remote pixels:
        self.assertEqual(window.capture_position, (500, 200))
        self.assertEqual(window.overlay, (500, 200))
        # the pointer is warped to the centre of the monitor:
        device = window.seat.get_pointer.return_value
        device.warp.assert_called_once_with(window.gdk_window.get_screen.return_value, *CENTER)
        # the click which starts the capture is not forwarded, neither is its release:
        window._button_action(1, event(50, 20), False)
        self.assertEqual(window.forwarded, [])
        # but the next one is:
        window._button_action(1, event(50, 20), True)
        window._button_action(1, event(50, 20), False)
        self.assertEqual(window.forwarded, [("button", 1, True), ("button", 1, False)])

    def test_requires_release_shortcut(self) -> None:
        window = CaptureTestWindow()
        self.assertEqual(window.get_release_shortcut(), "mod1+shift+Escape")
        window.subsystems["keyboard"].helper.key_shortcuts = {}
        window._button_action(1, event(50, 20), True)
        self.assertFalse(window.input_captured)
        window.seat.grab.assert_not_called()
        self.assertEqual(window.forwarded, [("button", 1, True)])

    def test_wheel_does_not_start_capture(self) -> None:
        window = CaptureTestWindow()
        window._button_action(4, event(50, 20), True)
        self.assertFalse(window.input_captured)
        self.assertEqual(window.forwarded, [("button", 4, True)])

    def test_capture_modes(self) -> None:
        for mode, can_capture in {
            "shadow": True,
            "X11 desktop": True,
            "seamless": False,
        }.items():
            self.assertEqual(CaptureTestWindow(server_mode=mode).can_input_capture(), can_capture, mode)
        self.assertFalse(CaptureTestWindow(input_capture=False).can_input_capture())
        window = CaptureTestWindow(server_mode="seamless")
        window._button_action(1, event(50, 20), True)
        self.assertFalse(window.input_captured)
        window.seat.grab.assert_not_called()

    def test_relative_motion(self) -> None:
        window = CaptureTestWindow()
        window._button_action(1, event(50, 20), True)
        window._button_action(1, event(50, 20), False)
        # the warp's own motion event does not move the remote pointer:
        window.motion(*CENTER)
        self.assertEqual(window.capture_position, (500, 200))
        self.assertEqual(window.sent_positions(), [])
        # then the pointer moves by 5 and 3 local pixels:
        window.motion(CENTER[0] + 5, CENTER[1] - 3)
        # which moves the remote pointer by 5 and 3 remote pixels, not 50 and 30:
        self.assertEqual(window.capture_position, (505, 197))
        self.assertEqual(window.sent_positions()[-1], (505, 197, 505, 197))
        self.assertEqual(window.forwarded, [])
        # button events use the virtual pointer position:
        self.assertEqual(window.get_pointer_data(event(0, 0)), (505, 197, 505, 197))

    def test_warp(self) -> None:
        window = CaptureTestWindow()
        window._button_action(1, event(50, 20), True)
        window.motion(*CENTER)
        device = window.seat.get_pointer.return_value
        device.warp.reset_mock()
        # small moves don't warp:
        window.motion(CENTER[0] + 40, CENTER[1])
        self.assertEqual(window.capture_position, (540, 200))
        device.warp.assert_not_called()
        # straying more than a quarter of the monitor from its centre warps back to the centre:
        window.motion(CENTER[0] + 250, CENTER[1])
        self.assertEqual(window.capture_position, (750, 200))
        device.warp.assert_called_once()
        # an event queued before the warp landed still counts from the previous position,
        # and does not warp again:
        window.motion(CENTER[0] + 260, CENTER[1])
        self.assertEqual(window.capture_position, (760, 200))
        device.warp.assert_called_once()
        # the warp's own event resets the position we measure from:
        window.motion(*CENTER)
        self.assertEqual(window.capture_position, (760, 200))
        window.motion(CENTER[0] + 40, CENTER[1] + 1)
        self.assertEqual(window.capture_position, (800, 201))

    def test_warp_retry(self) -> None:
        window = CaptureTestWindow()
        window._button_action(1, event(50, 20), True)
        device = window.seat.get_pointer.return_value
        # if the warp's own event never shows up, we warp again:
        for i in range(10):
            window.motion(CENTER[0] + 250 + i, CENTER[1])
        self.assertEqual(device.warp.call_count, 2)

    def test_release(self) -> None:
        window = CaptureTestWindow()
        window._button_action(1, event(50, 20), True)
        window._button_action(1, event(50, 20), False)
        window._button_action(3, event(50, 20), True)
        window.button_pressed[3] = 3
        window.toggle_input_capture()
        self.assertFalse(window.input_captured)
        self.assertFalse(window.subsystems["keyboard"].grabbed)
        window.seat.ungrab.assert_called_once()
        self.assertEqual(window.overlay, ())
        # the local pointer is shown where the remote one is:
        device = window.seat.get_pointer.return_value
        self.assertEqual(device.warp.call_args.args[1:], (ORIGIN[0] + 50, ORIGIN[1] + 20))
        # the button still held down is released on the server:
        send_button = window.subsystems["pointer"].send_button
        send_button.assert_called_once()
        self.assertEqual(send_button.call_args.args[2:4], (3, False))
        # motion events are forwarded again:
        window._do_motion_notify_event(event(10, 10))
        self.assertEqual(window.forwarded[-1], ("motion", 10, 10))
        # the shortcut captures again, from the centre:
        window.toggle_input_capture()
        self.assertTrue(window.input_captured)
        self.assertEqual(window.capture_position, (960, 540))

    def test_grab_broken(self) -> None:
        window = CaptureTestWindow()
        window._button_action(1, event(50, 20), True)
        # our own grab replacing the `GrabWindow` keyboard grab is not a loss:
        window.grab_broken(window, SimpleNamespace(grab_window=window.gdk_window))
        self.assertTrue(window.input_captured)
        window.grab_broken(window, SimpleNamespace(grab_window=None))
        self.assertFalse(window.input_captured)
        self.assertEqual(window.forwarded[-1], ("grab-broken", ))

    def test_leave_while_captured(self) -> None:
        window = CaptureTestWindow()
        window.on_leave_notify_event(window, None)
        self.assertEqual(window.forwarded, [("leave", )])
        window._button_action(1, event(50, 20), True)
        window.on_leave_notify_event(window, None)
        self.assertEqual(window.forwarded, [("leave", )])


def main():
    unittest.main()


if __name__ == '__main__':
    main()
