# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.server.subsystem.display import DisplayManager
from xpra.log import Logger

log = Logger("server", "wayland")


class WaylandDisplayManager(DisplayManager):

    def __init__(self, server=None):
        super().__init__(server)
        self.outputs = []

    def connect_compositor(self, compositor) -> None:
        compositor.connect("new-output", self.new_output)

    def new_output(self, output) -> None:
        log("new output %r=%r", output.name, output.get_info())
        self.outputs.append(output)

    def get_display_size(self) -> tuple[int, int]:
        width = height = 0
        for output in self.outputs:
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

    def publish_displayfd(self, display_name: str, fd: int) -> None:
        # the base implementation writes a numeric X11 display number;
        # wayland names like "wayland-1" are not numeric, so write them verbatim:
        from xpra.os_util import POSIX, OSX
        if not POSIX or OSX or fd <= 0:
            return
        from xpra.platform import displayfd
        displayfd.write_displayfd(fd, display_name)

    def get_display_description(self) -> str:
        details = ""
        outputs = list(self.outputs)
        if len(outputs) == 1:
            details = " " + outputs[0].get_description()
        return f"Wayland Display{details}"

    def get_wm_name(self) -> str:
        return "xpra on wayland"

    def get_ui_info(self, proto, **kwargs) -> dict:
        info = super().get_ui_info(proto, **kwargs)
        outputs = {
            i: output.get_info()
            for i, output in enumerate(self.outputs)
        }
        if outputs:
            info.setdefault("wayland", {})["outputs"] = outputs
        return info
