# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.server.subsystem.bell import BellServer
from xpra.log import Logger

log = Logger("server", "wayland", "bell")


class WaylandBellServer(BellServer):
    """
    Wayland servers that forward bell events.

    The compositor exposes the `xdg_system_bell_v1` global (see
    `WaylandCompositor.create_system_bell`) and emits a "bell" event with the
    surface the client rang the bell on - or 0 if it did not name one.
    """
    __slots__ = ()

    def connect_compositor(self, compositor) -> None:
        # note: `init(opts)` (which sets `self.bell`) runs *after*
        # `init_subsystems()`, so we always connect and let `send_bell`
        # decide whether the event is forwarded.
        compositor.connect("bell", self.bell_event)

    def bell_event(self, surface_ptr: int) -> None:
        # `xdg_system_bell_v1` carries no bell characteristics at all,
        # so everything but the window id is left at its default value:
        wid = self.get_wid(surface_ptr)
        log("bell_event(%#x) wid=%i", surface_ptr, wid)
        self.send_bell(wid)

    @staticmethod
    def get_wid(surface_ptr: int) -> int:
        if not surface_ptr:
            return 0
        from xpra.wayland.server.wayland_surface import surfaces
        surface = surfaces.get(surface_ptr)
        if surface is None:
            log("no surface found for %#x", surface_ptr)
            return 0
        return getattr(surface, "wid", 0)
