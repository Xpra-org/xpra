#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from dbus.types import UInt32, Int32

from xpra.dbus.helper import native_to_dbus
from xpra.pointer.nopointer import NoPointerDevice
from xpra.platform.posix.fd_portal import REMOTEDESKTOP_IFACE
from xpra.server.shadow.pointer import ShadowPointerManager
from xpra.log import Logger

log = Logger("shadow", "pointer")

# xdg-desktop-portal expects evdev button codes:
EVDEV_BUTTONS: dict[int, int] = {
    1: 0x110,  # BTN_LEFT
    2: 0x111,  # BTN_RIGHT
    3: 0x112,  # BTN_MIDDLE
}


class RemoteDesktopPointerManager(ShadowPointerManager):
    """
    Pointer subsystem injecting events via the `RemoteDesktop` portal interface.
    """

    def _portal_call(self, method: str, *args) -> None:
        server = self.server
        options = native_to_dbus([], "{sv}")
        getattr(server.portal_interface, method)(
            server.session_handle,
            options,
            *args,
            dbus_interface=REMOTEDESKTOP_IFACE)

    def _move_pointer(self, device_id: int, wid: int, pos, props=None) -> None:
        if not self.server.input_devices_count:
            return
        window_sub = self.get_subsystem("window")
        win = window_sub.get_window(wid) if window_sub else None
        if not win:
            log.error("Error: window %#x not found", wid)
            return
        x, y = pos[:2]
        self._portal_call("NotifyPointerMotionAbsolute", win.pipewire_id, x, y)

    def button_action(self, device_id: int, wid: int, button: int, pressed: bool, props: dict) -> None:
        if not self.server.input_devices_count:
            return
        log("button-action: button=%s, pressed=%s", button, pressed)
        evdev_button = EVDEV_BUTTONS.get(button, -1)
        if evdev_button < 0:
            log.warn("Warning: button %s not recognized", button)
            return
        self._portal_call("NotifyPointerButton", Int32(evdev_button), UInt32(pressed))
        self._update_button_state(device_id, button, pressed)


class ScreenCastPointerManager(ShadowPointerManager):
    """
    The `ScreenCast` portal interface has no input devices.
    """

    def make_pointer_device(self):
        return NoPointerDevice()
