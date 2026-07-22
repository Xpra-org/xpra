# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic

from xpra.platform.win32.common import SetPhysicalCursorPos
from xpra.server.shadow.pointer import ShadowPointerManager
from xpra.log import Logger

log = Logger("shadow", "win32")


class Win32ShadowPointerManager(ShadowPointerManager):
    """
    Win32 pointer subsystem for shadow servers.
    """

    def __init__(self, server=None):
        super().__init__(server)
        self.cursor_errors = [0.0, 0]

    def _move_pointer(self, device_id: int, wid: int, pos, props=None) -> None:
        x, y = pos[:2]
        try:
            if SetPhysicalCursorPos(x, y):
                return
            start, count = self.cursor_errors
            now = monotonic()
            elapsed = now - start
            if count == 0 or (count > 1 and elapsed > 10):
                log.warn("Warning: cannot move cursor")
                log.warn(" (%i events)", count + 1)
                self.cursor_errors = [now, 1]
            else:
                self.cursor_errors[1] = count + 1
        except Exception as e:
            log("SetPhysicalCursorPos%s failed", pos, exc_info=True)
            log.error("Error: failed to move the cursor:")
            log.estr(e)
