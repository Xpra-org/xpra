# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform.win32.gui import get_display_size
from xpra.server.shadow.display import ShadowDisplayManager


class Win32ShadowDisplayManager(ShadowDisplayManager):
    """
    Win32 display subsystem for shadow servers.
    """

    def get_display_size(self) -> tuple[int, int]:
        return get_display_size()
