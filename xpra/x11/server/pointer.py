# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util.objects import typedict
from xpra.x11.subsystem.pointer import X11PointerManager
from xpra.log import Logger

log = Logger("pointer")


class X11SeamlessPointerManager(X11PointerManager):
    """Resolve client monitor-relative pointer positions for seamless X11."""

    def get_pointer_target(self, proto, wid: int, pos, props=None) -> tuple[int, int]:
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
