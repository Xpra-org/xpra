# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import gi_import
from xpra.server.shadow.shadow_server_base import ShadowServerBase
from xpra.log import Logger

screenlog = Logger("screen")


class GTKShadowServerBase(ShadowServerBase):

    def get_shadow_monitors(self) -> list[tuple[str, int, int, int, int, int]]:
        Gdk = gi_import("Gdk")
        manager = Gdk.DisplayManager.get()
        display = manager.get_default_display()
        if not display:
            return []
        n = display.get_n_monitors()
        monitors = []
        for i in range(n):
            m = display.get_monitor(i)
            geom = m.get_geometry()
            try:
                scale_factor = m.get_scale_factor()
            except Exception as e:
                screenlog("no scale factor: %s", e)
                scale_factor = 1
            else:
                screenlog("scale factor for monitor %i: %i", i, scale_factor)
            plug_name = m.get_model()
            monitors.append((plug_name, geom.x, geom.y, geom.width, geom.height, scale_factor))
        screenlog("get_shadow_monitors()=%s", monitors)
        return monitors
