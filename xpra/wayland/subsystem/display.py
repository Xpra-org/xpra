# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.server.subsystem.display import DisplayManager


class WaylandDisplayManager(DisplayManager):

    def get_display_size(self) -> tuple[int, int]:
        return self.server.get_display_size()

    def get_display_description(self) -> str:
        details = ""
        outputs = list(self.server.outputs)
        if len(outputs) == 1:
            details = " " + outputs[0].get_description()
        return f"Wayland Display{details}"

    def get_wm_name(self) -> str:
        return "xpra on wayland"
