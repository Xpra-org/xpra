# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import gi_import
from xpra.util.env import envbool
from xpra.util.system import is_Wayland
from xpra.client.subsystem.display import DisplayClient

Gdk = gi_import("Gdk")


class Gtk3DisplayClient(DisplayClient):
    """
    GTK3 / GDK toolkit implementation of the display queries that need a real
    windowing toolkit binding (GDK abstracts X11/Wayland/win32-GDK/quartz-GDK
    uniformly, so no further per-OS split is needed here).
    """

    def get_root_size(self) -> tuple[int, int]:
        from xpra.gtk.util import get_root_size
        return get_root_size()

    def get_screen_sizes(self, xscale=1, yscale=1) -> list[tuple[int, int]]:
        from xpra.gtk.info import get_screen_sizes
        return get_screen_sizes(xscale, yscale)

    def has_transparency(self) -> bool:
        if not envbool("XPRA_ALPHA", True):
            return False
        screen = Gdk.Screen.get_default()
        if screen is None:
            return is_Wayland()
        return screen.get_rgba_visual() is not None
