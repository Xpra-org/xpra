# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys

from xpra.net.compression import Compressed
from xpra.server.common import make_icon_packet
from xpra.server.source.display import DisplayConnection
from xpra.server.subsystem.display import DisplayManager
from xpra.util.system import get_platform_icon_name
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

    def configure_best_screen_size(self) -> tuple[int, int]:
        max_w = max_h = 0
        client_sizes = {}
        for ss in self.get_sources_by_type(DisplayConnection):
            client_size = ss.desktop_size
            if client_size:
                w, h = client_size
                max_w = max(max_w, w)
                max_h = max(max_h, h)
                client_sizes[ss.uuid] = "%ix%i" % (w, h)
        if len(client_sizes) > 1:
            log.info("wayland screen used by %i clients:", len(client_sizes))
            for uuid, size in client_sizes.items():
                log.info("* %s: %s", uuid, size)
        if max_w <= 0 or max_h <= 0:
            return self.get_display_size()
        return self.set_screen_size(max_w, max_h)

    def set_screen_size(self, width: int, height: int) -> tuple[int, int]:
        log("set_screen_size%s", (width, height))
        if not self.outputs:
            return width, height
        output = self.outputs[0]
        try:
            root_w, root_h = output.resize(width, height)
        except Exception as e:
            log("output.resize%s", (width, height), exc_info=True)
            log.warn("Warning: failed to resize wayland output to %ix%i:", width, height)
            log.warn(" %s", e)
            return self.get_display_size()
        if len(self.outputs) > 1:
            log.warn("Warning: ignoring %i extra wayland outputs for simple resize",
                     len(self.outputs) - 1)
        self.notify_screen_changed()
        return root_w, root_h

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

    def do_make_icon_packet(self) -> tuple[str, int, int, str, int, Compressed]:
        names: list[str] = []
        session_name = getattr(self.server, "session_name", "")
        if session_name:
            try:
                from xpra.platform.posix.menu_helper import find_icon
                if filename := find_icon(session_name):
                    names.append(filename)
            except ImportError:
                log("find_icon not available", exc_info=True)
        names += [get_platform_icon_name(sys.platform), "server.png", "xpra.png"]
        return make_icon_packet(*names)

    def get_ui_info(self, proto, **kwargs) -> dict:
        info = super().get_ui_info(proto, **kwargs)
        outputs = {
            i: output.get_info()
            for i, output in enumerate(self.outputs)
        }
        if outputs:
            info.setdefault("wayland", {})["outputs"] = outputs
        return info
