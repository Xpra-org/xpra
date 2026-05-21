# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.server.subsystem.clipboard import ClipboardManager


class WaylandClipboardManager(ClipboardManager):

    def get_clipboard_class(self):
        from xpra.wayland.clipboard import WaylandClipboard

        def make_wayland_clipboard(*args, **kwargs) -> WaylandClipboard:
            return WaylandClipboard(*args, compositor=self.server.compositor, **kwargs)

        return make_wayland_clipboard
