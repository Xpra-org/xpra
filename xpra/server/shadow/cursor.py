# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Sequence

from xpra.server.subsystem.cursor import CursorManager
from xpra.util.env import envbool
from xpra.log import Logger

cursorlog = Logger("cursor")

CURSORS = envbool("XPRA_CURSORS", True)
SAVE_CURSORS = envbool("XPRA_SAVE_CURSORS", False)


class ShadowCursorManager(CursorManager):
    """
    Cursor subsystem for shadow servers.

    Shadow backends usually cannot rely on cursor-change events, so they cache
    the cursor data found while polling the pointer position.
    """

    def __init__(self, server=None):
        super().__init__(server)
        self.last_cursor_data = None

    def poll_cursor(self) -> None:
        if not self.enabled or not CURSORS:
            return
        prev = self.last_cursor_data
        curr = self.do_get_cursor_data()  # pylint: disable=assignment-from-none
        self.last_cursor_data = curr
        self.last_image = curr[0] if curr and curr[0] else ()

        def cmpv(lcd: Sequence | None) -> tuple[Any, ...]:
            if not lcd:
                return ()
            v = lcd[0]
            if v and len(v) > 2:
                return tuple(v[2:])
            return ()

        if cmpv(prev) != cmpv(curr):
            self.log_cursor_change(prev, curr)
            for ss in tuple(self.server._server_sources.values()):
                # not all client connections support `send_cursor`,
                # only a CursorsConnection, or a RFBSource do:
                if send_cursor := getattr(ss, "send_cursor", None):
                    send_cursor()

    def log_cursor_change(self, prev, curr) -> None:
        fields = ("x", "y", "width", "height", "xhot", "yhot", "serial", "pixels", "name")
        prev_ci = prev[0] if prev else ()
        curr_ci = curr[0] if curr else ()
        if len(prev_ci or ()) == len(curr_ci or ()) == len(fields):
            diff = []
            for i, prev_value in enumerate(prev_ci):
                if prev_value != curr_ci[i]:
                    diff.append(fields[i])
            cursorlog("poll_cursor() attributes changed: %s", diff)
        if SAVE_CURSORS and curr:
            ci = curr[0]
            if ci:
                w = ci[2]
                h = ci[3]
                serial = ci[6]
                pixels = ci[7]
                cursorlog("saving cursor %#x with size %ix%i, %i bytes", serial, w, h, len(pixels))
                from PIL import Image
                img = Image.frombuffer("RGBA", (w, h), pixels, "raw", "BGRA", 0, 1)
                img.save("cursor-%#x.png" % serial, format="PNG")

    def do_get_cursor_data(self):
        # this method is overridden in subclasses with platform specific code
        return None

    def get_cursor_data(self, skip_default=True):
        # return cached value we get from polling:
        return self.last_cursor_data
