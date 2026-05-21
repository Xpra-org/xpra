# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Sequence

from xpra.net.common import Packet
from xpra.server.subsystem.pointer import PointerManager
from xpra.log import Logger

log = Logger("server", "wayland")


class WaylandPointerManager(PointerManager):

    def make_pointer_device(self):
        return self.server.compositor.get_pointer_device()

    def cleanup(self) -> None:
        if device := self.pointer_device:
            device.cleanup()
        self.pointer_device = None
        self.pointer_device_map = {}

    def set_pointer_focus(self, wid: int, pointer: Sequence) -> None:
        server = self.server
        window = server.subsystems["window"]
        log("set_pointer_focus(%i, %s)", wid, pointer)
        if window.pointer_focus == wid:
            log(" focus unchanged")
            return
        log(" current focus=%i", window.pointer_focus)
        if window.pointer_focus and wid == 0:
            self.pointer_device.leave_surface()
            window.pointer_focus = 0
            return
        surface = window.get_surface(wid)
        log("surface(%i)=%s", wid, surface)
        if surface and len(pointer) >= 4 and (ptr := surface.xdg_surface_ptr):
            x, y = pointer[2:4]
            if self.pointer_device.enter_surface(ptr, x, y):
                window.pointer_focus = wid
        server.compositor.flush()

    def do_process_mouse_common(self, proto, device_id: int, wid: int, pointer, props) -> bool:
        keyboard = self.server.subsystems.get("keyboard")
        if props and "modifiers" in props and keyboard:
            keyboard.update_keyboard_modifiers(props.get("modifiers", ()))
        self.set_pointer_focus(wid, pointer)
        log("pointer: %r", pointer)
        try:
            if self.server.readonly:
                return False
            if pointer:
                if len(pointer) >= 4:
                    x, y = pointer[2:4]
                else:
                    x, y = pointer[:2]
                self.get_pointer_device(device_id).move_pointer(x, y, props or {})
            return True
        finally:
            self.server.compositor.flush()

    def _update_modifiers(self, proto, wid: int, modifiers: Sequence[str]) -> None:
        keyboard = self.server.subsystems.get("keyboard")
        if keyboard:
            keyboard.update_keyboard_modifiers(modifiers)
        super()._update_modifiers(proto, wid, modifiers)

    def button_action(self, device_id: int, wid: int, button: int, pressed: bool, props: dict) -> None:
        try:
            super().button_action(device_id, wid, button, pressed, props)
        finally:
            self.server.compositor.flush()

    def _process_pointer_wheel(self, proto, packet: Packet) -> None:
        try:
            super()._process_pointer_wheel(proto, packet)
        finally:
            self.server.compositor.flush()
