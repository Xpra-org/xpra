# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.server.subsystem.pointer import PointerManager
from xpra.log import Logger

pointerlog = Logger("pointer")


class ShadowPointerMixin:
    def suspend_cursor(self, proto) -> None:
        if cursor := self.get_subsystem("cursor"):
            cursor.suspend_cursor(proto)

    def restore_cursor(self, proto) -> None:
        if cursor := self.get_subsystem("cursor"):
            cursor.restore_cursor(proto)

    def _adjust_pointer(self, proto, device_id, wid: int, opointer) -> list[int] | None:
        window = self.get_subsystem("window").get_window(wid)
        if wid > 0 and not window:
            self.suspend_cursor(proto)
            return None
        pointer = super()._adjust_pointer(proto, device_id, wid, opointer)
        ax = x = int(pointer[0])
        ay = y = int(pointer[1])
        if window:
            # The window may be at an offset (multi-window for multi-monitor).
            wx, wy, ww, wh = window.get_geometry()
            if x < 0 or x >= ww or y < 0 or y >= wh:
                self.suspend_cursor(proto)
                return None
            # X11 shadow recalculates absolute coordinates from the relative
            # ones, and should end up with the same values calculated here.
            ax = x + wx
            ay = y + wy
        self.restore_cursor(proto)
        return [ax, ay] + list(pointer[2:])


class ShadowPointerManager(ShadowPointerMixin, PointerManager):
    """
    Pointer subsystem for shadow servers.
    """
