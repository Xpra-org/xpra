# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any

from xpra.os_util import gi_import, OSX
from xpra.common import may_notify_client
from xpra.constants import NotificationID
from xpra.util.objects import typedict
from xpra.util.env import envbool, envfloat
from xpra.client.gui.keyboard_shortcuts_parser import get_modifier_labels, shortcut_keys_str
from xpra.client.gtk3.window.stub_window import GtkStubWindow
from xpra.client.gtk3.window.common import mask_buttons
from xpra.log import Logger

Gdk = gi_import("Gdk")

log = Logger("window", "grab", "pointer")

CAPTURE_MODES = os.environ.get("XPRA_INPUT_CAPTURE_MODES", "shadow,desktop,monitor").split(",")
CAPTURE_SENSITIVITY = envfloat("XPRA_INPUT_CAPTURE_SENSITIVITY", 1.0)
# events this far from the centre of the monitor trigger a warp back to the centre:
CAPTURE_WARP_MARGIN = envfloat("XPRA_INPUT_CAPTURE_WARP_MARGIN", 0.125)
# warping the pointer generates a motion event at the warp position, except on macOS:
CAPTURE_WARP_EVENTS = envbool("XPRA_INPUT_CAPTURE_WARP_EVENTS", not OSX)
# warp again if we don't see the warp's motion event after this many motion events:
CAPTURE_WARP_RETRY = 8
# the buttons which start the capture (not the wheel buttons):
CAPTURE_BUTTONS = (1, 2, 3)


def accumulate(position: tuple[float, float], delta: tuple[float, float], size: tuple[int, int],
               sensitivity: float = CAPTURE_SENSITIVITY) -> tuple[float, float]:
    """
    Move the virtual remote pointer `position` by the local `delta`,
    keeping it within a remote window of the given `size`.
    """
    w, h = size
    x = min(max(0.0, position[0] + delta[0] * sensitivity), max(0, w - 1))
    y = min(max(0.0, position[1] + delta[1] * sensitivity), max(0, h - 1))
    return x, y


class CaptureWindow(GtkStubWindow):
    """
    Input capture for (small, scaled down) shadow and desktop windows:
    clicking the window grabs the local pointer and keyboard,
    local pointer motion is turned into relative motion of a virtual pointer
    that moves over the remote desktop at its native resolution,
    until `toggle_input_capture` releases it.
    This class must come before `GrabWindow` and `PointerWindow` in the window bases,
    so that its methods take precedence.
    """

    def init_window(self, client, metadata: typedict, client_props: typedict) -> None:
        self.input_captured = False
        # the virtual remote pointer, in window-relative server coordinates:
        self.capture_position: tuple[float, float] = (0, 0)
        # the last local position seen, in root coordinates:
        self.capture_last: tuple[float, float] = (0, 0)
        # where we warp the local pointer to (root coordinates), and how far it may stray from there:
        self.capture_warp: tuple[int, int, int] = (0, 0, 0)
        self.capture_warp_pending = 0
        # the window's event mask before the capture:
        self.capture_events = 0
        # the local button which started the capture, so we can swallow its release:
        self.capture_button = -1

    def cleanup(self) -> None:
        self.release_input_capture()

    def get_info(self) -> dict[str, Any]:
        return {
            "input-capture": {
                "enabled": self.can_input_capture(),
                "captured": self.input_captured,
                "position": tuple(round(v) for v in self.capture_position),
            },
        }

    def can_input_capture(self) -> bool:
        pointer = self.get_subsystem("pointer")
        if not pointer or not getattr(pointer, "input_capture", False):
            return False
        if self._override_redirect or self._client.readonly or self._client.server_readonly:
            return False
        remoteinfo = self._client.get_subsystem("remote-info")
        server_mode = remoteinfo._remote_server_mode if remoteinfo else ""
        return any(x == "*" or server_mode.find(x) >= 0 for x in CAPTURE_MODES)

    def get_capture_size(self) -> tuple[int, int]:
        # the size of the remote window, in server pixels:
        return self.cp(*self._size)

    def get_capture_center(self) -> tuple[int, int]:
        w, h = self._size
        return w // 2, h // 2

    def toggle_input_capture(self, *_args) -> None:
        log("toggle_input_capture() captured=%s", self.input_captured)
        if self.input_captured:
            self.release_input_capture()
        else:
            x, y = self.get_capture_center()
            self.start_input_capture(x, y)

    def start_input_capture(self, x: float, y: float) -> bool:
        if self.input_captured or not self.can_input_capture():
            return False
        gdkwin = self.get_capture_gdk_window()
        display = gdkwin.get_display() if gdkwin else None
        seat = display.get_default_seat() if display else None
        if not seat:
            log("start_input_capture: no seat")
            return False
        if type(display).__name__.find("Wayland") >= 0:
            # GTK3 cannot warp the pointer on Wayland:
            log.warn("Warning: input capture is not supported on Wayland")
            return False
        release = self.get_release_shortcut()
        if not release:
            # we would have no way out:
            log.warn("Warning: input capture requires a 'toggle_input_capture' key shortcut")
            log.warn(" ie: --key-shortcut=#+Escape:toggle_input_capture")
            return False
        # hide the local cursor, the pointer overlay shows the remote one:
        cursor = self.get_capture_cursor(display)
        r = seat.grab(gdkwin, Gdk.SeatCapabilities.ALL, True, cursor, None, None, None)
        log("start_input_capture(%s, %s) %s.grab(..)=%s", x, y, seat, r)
        if r != Gdk.GrabStatus.SUCCESS:
            log.warn("Warning: failed to capture the pointer and keyboard: %s", r)
            return False
        self.input_captured = True
        # GTK merges consecutive motion events, and so does the X server with motion hints,
        # either one could hide the warp's own event:
        gdkwin.set_event_compression(False)
        self.capture_events = gdkwin.get_events()
        gdkwin.set_events(self.capture_events & ~Gdk.EventMask.POINTER_MOTION_HINT_MASK)
        if kb := self.get_subsystem("keyboard"):
            kb.grabbed = True
        self.capture_position = self.cp(x, y)
        ox, oy = gdkwin.get_origin()[-2:]
        self.capture_last = (ox + x, oy + y)
        self.capture_warp = self.get_capture_warp(gdkwin, display)
        self.capture_warp_pending = 0
        self.warp_to_center()
        self.show_pointer_overlay(tuple(round(v) for v in self.capture_position))
        log.info("input capture started, press %s to release it", release)
        may_notify_client(self._client, NotificationID.INPUT_CAPTURE, "Input capture started",
                          f"Press {release} to release the pointer and keyboard.",
                          hints={"transient": True}, expire_timeout=5000, icon_name="keyboard")
        return True

    def get_capture_gdk_window(self):
        # grab with the window of the widget handling the pointer events,
        # so the events outside the window are reported to it:
        # (key events are always sent to the toplevel window)
        if (da := getattr(self, "drawing_area", None)) and (window := da.get_window()):
            return window
        return self.get_window()

    @staticmethod
    def get_capture_warp(gdkwin, display) -> tuple[int, int, int]:
        # warp to the centre of the monitor rather than the window,
        # so the local pointer has plenty of room before it hits the edge of the screen,
        # where the X server would discard the motion:
        geom = display.get_monitor_at_window(gdkwin).get_geometry()
        margin = max(1, round(min(geom.width, geom.height) * CAPTURE_WARP_MARGIN))
        return geom.x + geom.width // 2, geom.y + geom.height // 2, margin

    @staticmethod
    def get_capture_cursor(display):
        return Gdk.Cursor.new_for_display(display, Gdk.CursorType.BLANK_CURSOR)

    def get_release_shortcut(self) -> str:
        if (kb := self.get_subsystem("keyboard")) and (helper := getattr(kb, "helper", None)):
            for key, shortcuts in getattr(helper, "key_shortcuts", {}).items():
                for req_mods, action, _args in shortcuts:
                    if action == "toggle_input_capture":
                        mod_labels = get_modifier_labels(helper.get_modifier_names())
                        return shortcut_keys_str(key, req_mods, mod_labels)
        return ""

    def release_input_capture(self) -> None:
        if not self.input_captured:
            return
        log("release_input_capture()")
        self.input_captured = False
        self.capture_button = -1
        self.capture_warp_pending = 0
        # release any buttons still held down on the server:
        for button in tuple(self.button_pressed.keys()):
            self.send_capture_button(button, False)
        if gdkwin := self.get_capture_gdk_window():
            gdkwin.set_event_compression(True)
            if self.capture_events:
                gdkwin.set_events(self.capture_events)
                self.capture_events = 0
            if display := gdkwin.get_display():
                if seat := display.get_default_seat():
                    seat.ungrab()
                    # show the local pointer where the remote one is in the window:
                    if device := seat.get_pointer():
                        ox, oy = gdkwin.get_origin()[-2:]
                        x, y = self.sp(*(round(v) for v in self.capture_position))
                        device.warp(gdkwin.get_screen(), ox + x, oy + y)
        if kb := self.get_subsystem("keyboard"):
            kb.grabbed = False
        self.show_pointer_overlay()
        log.info("input capture released")

    def send_capture_button(self, button: int, pressed: bool) -> None:
        pointer = self.get_subsystem("pointer")
        if not pointer:
            return
        server_button = self.button_pressed.pop(button, button)
        pointer_data = self.get_capture_pointer_data()
        pointer.send_button(0, self.wid, server_button, pressed, pointer_data, [], [], {})

    def warp_to_center(self) -> None:
        gdkwin = self.get_capture_gdk_window()
        display = gdkwin.get_display() if gdkwin else None
        seat = display.get_default_seat() if display else None
        device = seat.get_pointer() if seat else None
        if not device:
            return
        cx, cy = self.capture_warp[:2]
        device.warp(gdkwin.get_screen(), cx, cy)
        if CAPTURE_WARP_EVENTS:
            # the events already queued are still measured from the previous position:
            self.capture_warp_pending = CAPTURE_WARP_RETRY
        else:
            self.capture_last = (cx, cy)

    def get_capture_pointer_data(self) -> tuple[int, int, int, int]:
        rx, ry = (round(v) for v in self.capture_position)
        ox, oy = self.cp(*self._pos)
        return ox + rx, oy + ry, rx, ry

    def capture_motion(self, event) -> bool:
        """
        Turns the local motion event into relative motion of the virtual pointer.
        Returns False if the input is not captured.
        """
        if not self.input_captured:
            return False
        x, y = event.x_root, event.y_root
        cx, cy, margin = self.capture_warp
        log("capture_motion(%s) position=%s, last=%s, warp-pending=%i",
            (x, y), self.capture_position, self.capture_last, self.capture_warp_pending)
        if self.capture_warp_pending:
            if round(x) == cx and round(y) == cy:
                # this is the motion event generated by the warp itself:
                self.capture_warp_pending = 0
                self.capture_last = (cx, cy)
                return True
            self.capture_warp_pending -= 1
        lx, ly = self.capture_last
        self.capture_last = (x, y)
        # the deltas are local pixels, which we apply to the remote pointer unscaled:
        self.capture_position = accumulate(self.capture_position, (x - lx, y - ly), self.get_capture_size())
        if not self.capture_warp_pending and (abs(x - cx) > margin or abs(y - cy) > margin):
            self.warp_to_center()
        self.send_capture_position(event)
        return True

    def send_capture_position(self, event) -> None:
        pointer = self.get_subsystem("pointer")
        if not pointer:
            return
        keyboard = self.get_subsystem("keyboard")
        state = getattr(event, "state", 0)
        modifiers = keyboard.mask_to_names(state) if keyboard else []
        buttons = mask_buttons(state)
        pointer_data = self.get_capture_pointer_data()
        log("capture motion: %s", pointer_data)
        pointer.send_mouse_position(0, self.wid, pointer_data, modifiers, buttons)
        self.show_pointer_overlay(pointer_data[2:4])

    ######################################################################
    # overrides of the `PointerWindow` and `GrabWindow` methods:

    def _do_motion_notify_event(self, event) -> None:
        if not self.capture_motion(event):
            super()._do_motion_notify_event(event)

    def get_pointer_data(self, event) -> tuple[int, int, int, int]:
        if self.input_captured:
            return self.get_capture_pointer_data()
        return super().get_pointer_data(event)

    def _button_action(self, button: int, event, depressed: bool, props=None) -> None:
        if not self.input_captured:
            if depressed and button in CAPTURE_BUTTONS and self.start_input_capture(event.x, event.y):
                # this click only starts the capture, it is not forwarded:
                self.capture_button = button
                return
        elif not depressed and button == self.capture_button:
            self.capture_button = -1
            return
        super()._button_action(button, event, depressed, props)

    def on_leave_notify_event(self, window, event) -> None:
        if self.input_captured:
            # the pointer only leaves between two warps, don't let `GrabWindow` ungrab the keyboard:
            return
        super().on_leave_notify_event(window, event)

    def grab_broken(self, win, event) -> None:
        log("grab_broken%s captured=%s", (win, event), self.input_captured)
        own_windows = (self.get_window(), self.get_capture_gdk_window())
        if self.input_captured and getattr(event, "grab_window", None) not in own_windows:
            # (when the new grab is on our own window, we replaced the `GrabWindow` keyboard grab)
            # the grab is gone already, just update our state:
            self.input_captured = False
            self.capture_button = -1
            if kb := self.get_subsystem("keyboard"):
                kb.grabbed = False
            self.show_pointer_overlay()
        super().grab_broken(win, event)
