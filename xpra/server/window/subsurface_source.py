# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.server.window.video_compress import WindowVideoSource


class SubsurfaceWindowSource(WindowVideoSource):
    """A WindowSource that encodes pixels for a wayland subsurface but emits
    draw packets targeting the parent toplevel window. The subsurface keeps
    its own wid for internal state (damage, batch delay, encoder pipeline)
    while outbound packets carry the parent's wid and parent-relative
    coordinates."""

    def __init__(self, *args, parent_wid: int, offset_x: int, offset_y: int, **kwargs):
        super().__init__(*args, **kwargs)
        self.parent_wid = parent_wid
        self.offset_x = offset_x
        self.offset_y = offset_y

    def update_geometry(self, parent_wid: int, offset_x: int, offset_y: int) -> None:
        self.parent_wid = parent_wid
        self.offset_x = offset_x
        self.offset_y = offset_y

    def _draw_packet_target(self, x: int, y: int) -> tuple[int, int, int]:
        return self.parent_wid, x + self.offset_x, y + self.offset_y

    def schedule_auto_refresh(self, packet, options) -> None:
        # No-op: outbound draw packets carry parent-relative coords (we
        # rewrite wid+offset in `_draw_packet_target`). The base
        # implementation would feed those parent-coord rectangles back
        # through `damage()`, where they'd be clipped against the
        # subsurface's local dimensions and produce garbage refreshes.
        # Re-enable later by translating the region from parent-coords to
        # subsurface-local coords first.
        return
