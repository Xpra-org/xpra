# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.os_util import gi_import
from xpra.x11.error import xswallow, xlog
from xpra.x11.server.core import X11ServerCore
from xpra.x11.server.xtest_pointer import XTestPointerDevice
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("x11", "server")
pointerlog = Logger("x11", "server", "pointer")
screenlog = Logger("server", "screen")


class X11ServerBase(X11ServerCore):
    """
        Base class for X11 servers,
        adds uinput, icc and xsettings synchronization to the X11ServerCore class
        (see XpraServer or DesktopServer for actual implementations)
    """

    def __init__(self):
        super().__init__()
        self.input_devices = "xtest"

    # noinspection PyMethodMayBeStatic
    def clean_x11_properties(self) -> None:
        super().clean_x11_properties()
        self.do_clean_x11_properties("XPRA_SERVER_PID")

    def configure_best_screen_size(self) -> tuple[int, int]:
        root_w, root_h = super().configure_best_screen_size()
        if self.touchpad_device:
            self.touchpad_device.root_w = root_w
            self.touchpad_device.root_h = root_h
        return root_w, root_h

    def init_virtual_devices(self, devices: dict[str, Any]) -> None:
        # pylint: disable=import-outside-toplevel
        # (this runs in the main thread - before the main loop starts)
        # for the time being, we only use the pointer if there is one:
        if not hasattr(self, "get_display_size"):
            log.warn("cannot enable virtual devices without a display")
            return
        pointer = devices.get("pointer")
        touchpad = devices.get("touchpad")
        pointerlog("init_virtual_devices(%s) got pointer=%s, touchpad=%s", devices, pointer, touchpad)
        self.input_devices = "xtest"
        if pointer:
            uinput_device = pointer.get("uinput")
            device_path = pointer.get("device")
            if uinput_device:
                from xpra.x11.uinput.device import UInputPointerDevice
                self.input_devices = "uinput"
                self.pointer_device = UInputPointerDevice(uinput_device, device_path)
                self.verify_uinput_pointer_device()
        if self.input_devices == "uinput" and touchpad:
            uinput_device = touchpad.get("uinput")
            device_path = touchpad.get("device")
            if uinput_device:
                from xpra.x11.uinput.device import UInputTouchpadDevice
                root_w, root_h = self.get_display_size()
                self.touchpad_device = UInputTouchpadDevice(uinput_device, device_path, root_w, root_h)
        try:
            pointerlog.info("pointer device emulation using %s", str(self.pointer_device).replace("PointerDevice", ""))
        except Exception as e:
            pointerlog("cannot get pointer device class from %s: %s", self.pointer_device, e)

    def verify_uinput_pointer_device(self) -> None:
        xtest = XTestPointerDevice()
        ox, oy = 100, 100
        with xlog:
            xtest.move_pointer(ox, oy, {})
        nx, ny = 200, 200
        self.pointer_device.move_pointer(nx, ny, {})

        def verify_uinput_moved() -> None:
            pos = (ox, oy)
            with xswallow:
                from xpra.x11.bindings.keyboard import X11KeyboardBindings
                pos = X11KeyboardBindings().query_pointer()
                pointerlog("X11Keyboard.query_pointer=%s", pos)
            if pos == (ox, oy):
                pointerlog.warn("Warning: %s failed verification", self.pointer_device)
                pointerlog.warn(" expected pointer at %s, now at %s", (nx, ny), pos)
                pointerlog.warn(" using XTest fallback")
                self.pointer_device = xtest
                self.input_devices = "xtest"

        GLib.timeout_add(1000, verify_uinput_moved)

    def dpi_changed(self) -> None:
        # re-apply the same settings, which will apply the new dpi override to it:
        self.update_server_settings()

    def get_info(self, proto=None, client_uuids=None) -> dict[str, Any]:
        info = super().get_info(proto=proto, client_uuids=client_uuids)
        display_info = info.setdefault("display", {})
        if self.display_pid:
            display_info["pid"] = self.display_pid
        return info
