# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.server.subsystem.clipboard import ClipboardManager
from xpra.log import Logger

log = Logger("wayland", "clipboard")


class WaylandClipboardManager(ClipboardManager):

    def get_clipboard_class(self):
        try:
            from xpra.wayland.clipboard import WaylandClipboard
        except ImportError as e:
            log("get_clipboard_class()", exc_info=True)
            log.warn("Warning: unable to load the Wayland clipboard backend")
            log.warn(" %s", e)
            return None

        def make_wayland_clipboard(*args, **kwargs) -> WaylandClipboard:
            return WaylandClipboard(*args, compositor=self.server.compositor, **kwargs)

        return make_wayland_clipboard
