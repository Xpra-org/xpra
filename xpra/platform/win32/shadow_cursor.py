# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from ctypes import sizeof, byref

from xpra.platform.win32 import constants as win32con
from xpra.platform.win32.common import GetCursorInfo, CURSORINFO
from xpra.platform.win32.gui import get_fixed_cursor_size
from xpra.platform.win32.shadow.cursor import get_cursor_data
from xpra.server.shadow.cursor import ShadowCursorManager
from xpra.log import Logger

cursorlog = Logger("cursor")


class Win32ShadowCursorManager(ShadowCursorManager):
    """
    Win32 cursor subsystem for shadow servers.
    """

    def __init__(self, server=None):
        super().__init__(server)
        self.cursor_handle = None

    def do_get_cursor_data(self) -> tuple | None:
        ci = CURSORINFO()
        ci.cbSize = sizeof(CURSORINFO)
        GetCursorInfo(byref(ci))
        # cursorlog("GetCursorInfo handle=%#x, last handle=%#x", ci.hCursor or 0, self.cursor_handle or 0)
        if not (ci.flags & win32con.CURSOR_SHOWING):
            # cursorlog("do_get_cursor_data() cursor not shown")
            return None
        handle = int(ci.hCursor)
        if handle == self.cursor_handle and self.last_cursor_data:
            # cursorlog("do_get_cursor_data() cursor handle unchanged")
            return self.last_cursor_data
        self.cursor_handle = handle
        cd = get_cursor_data(handle)
        if not cd:
            cursorlog("do_get_cursor_data() no cursor data")
            return self.last_cursor_data
        cd[0] = ci.ptScreenPos.x
        cd[1] = ci.ptScreenPos.y
        w, h = get_fixed_cursor_size()
        return (
            cd,
            ((w, h), [(w, h), ]),
        )
