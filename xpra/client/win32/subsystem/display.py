# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Sequence

from xpra.platform.win32.monitors import get_monitors_info
from xpra.client.subsystem.display import DisplayClient
from xpra.log import Logger

log = Logger("win32", "screen")


class Win32DisplayClient(DisplayClient):
    """
    win32-native (non-GTK) toolkit implementation of the display queries that
    need real window-system bindings.
    """

    def get_root_size(self) -> tuple[int, int]:
        from xpra.platform.win32.gui import get_display_size
        return get_display_size()

    def get_screen_sizes(self, xscale=1.0, yscale=1.0) -> Sequence[tuple[int, int]]:
        w, h = self.get_root_size()
        return ((round(w / xscale), round(h / yscale)), )

    def get_monitors_info(self) -> dict:
        return get_monitors_info(self.xscale, self.yscale)
