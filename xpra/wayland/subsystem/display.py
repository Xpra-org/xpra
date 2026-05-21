# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.server.subsystem.display import DisplayManager


class WaylandDisplayManager(DisplayManager):

    def get_display_size(self) -> tuple[int, int]:
        width = height = 0
        for output in self.server.outputs:
            info = output.get_info()
            lx = info.get("logical-x", 0)
            ly = info.get("logical-y", 0)
            lw = info.get("logical-width", info.get("width", 0))
            lh = info.get("logical-height", info.get("height", 0))
            width = max(width, lx + lw)
            height = max(height, ly + lh)
        return width, height

    def get_display_name(self) -> str:
        wd = os.environ.get("WAYLAND_DISPLAY", "")
        parts = wd.split("-", 1)
        if len(parts) == 2:
            return parts[1]
        return wd

    def get_display_description(self) -> str:
        details = ""
        outputs = list(self.server.outputs)
        if len(outputs) == 1:
            details = " " + outputs[0].get_description()
        return f"Wayland Display{details}"

    def get_wm_name(self) -> str:
        return "xpra on wayland"
