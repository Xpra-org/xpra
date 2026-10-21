# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util.objects import typedict
from xpra.x11.subsystem.pointer import X11PointerManager
from xpra.log import Logger

log = Logger("pointer")


class X11SeamlessPointerManager(X11PointerManager):
    """Resolve seamless X11 pointer positions, preferring window-relative coordinates."""

    # The target window must be raised even when the pointer position is unchanged.
    SKIP_REDUNDANT_MOVES = False

    def _move_pointer(self, device_id: int, wid: int, pos, props=None) -> None:
        window = self.get_subsystem("window")
        if window:
            window.raise_window_under_pointer(wid)
        super()._move_pointer(device_id, wid, pos, props)

    def get_pointer_target(self, proto, wid: int, pos, props=None) -> tuple[int, int]:
        if self.get_pointer_window_position(pos, props) is not None:
            windows = self.get_subsystem("window")
            if windows and windows.get_window(wid):
                # Wayland root coordinates are not reliable desktop positions.
                # Use the server window's origin plus the position inside it.
                return super().get_pointer_target(proto, wid, pos, props)
        ss = self.get_server_source(proto)
        monitor_value = (props or {}).get("monitor", {})
        monitor = typedict(monitor_value if isinstance(monitor_value, dict) else {})
        if ss and hasattr(ss, "get_monitor_position") and monitor:
            index = monitor.intget("index", -1)
            position = monitor.inttupleget("position")
            if len(position) == 2 and (resolved := ss.get_monitor_position(index, position)):
                log("resolved client monitor %i pointer position %s to %s", index, position, resolved)
                return resolved
        return super().get_pointer_target(proto, wid, pos, props)
