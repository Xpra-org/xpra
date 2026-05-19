# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.x11.error import xsync
from xpra.x11.subsystem.pointer import X11PointerManager
from xpra.log import Logger

pointerlog = Logger("server", "pointer")


class XpraDesktopPointerManager(X11PointerManager):
    """
    Pointer subsystem for desktop and monitor servers.
    """

    def suspend_cursor(self, proto) -> None:
        if cursor := self.get_subsystem("cursor"):
            cursor.suspend_cursor(proto)

    def restore_cursor(self, proto) -> None:
        if cursor := self.get_subsystem("cursor"):
            cursor.restore_cursor(proto)

    def _adjust_pointer(self, proto, device_id: int, wid: int, pointer):
        pointerlog("_adjust_pointer%s", (proto, device_id, wid, pointer))
        window_sub = self.get_subsystem("window")
        window = window_sub.get_window(wid) if window_sub else None
        if not window:
            pointerlog("adjust pointer: no window, suspending cursor")
            self.suspend_cursor(proto)
            return None
        pointer = super()._adjust_pointer(proto, device_id, wid, pointer)
        ww, wh = window.get_dimensions()
        x, y = pointer[:2]
        if x < 0 or x >= ww or y < 0 or y >= wh:
            pointerlog("adjust pointer: pointer outside desktop, suspending cursor")
            self.suspend_cursor(proto)
            return None
        self.restore_cursor(proto)
        return pointer

    def _move_pointer(self, device_id: int, wid: int, pos, props=None) -> None:
        if wid >= 0:
            window_sub = self.get_subsystem("window")
            window = window_sub.get_window(wid) if window_sub else None
            if not window:
                pointerlog("_move_pointer(%s, %s) invalid window id", wid, pos)
                return
        with xsync:
            super()._move_pointer(device_id, wid, pos, props)
