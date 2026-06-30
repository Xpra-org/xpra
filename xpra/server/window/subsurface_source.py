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

    def __init__(self, *args, parent_wid: int, offset_x: int, offset_y: int,
                 logical_width: int = 0, logical_height: int = 0,
                 native_width: int = 0, native_height: int = 0):
        super().__init__(*args)
        self.parent_wid = parent_wid
        self.offset_x = offset_x
        self.offset_y = offset_y
        self.logical_width = logical_width
        self.logical_height = logical_height
        self.native_width = native_width
        self.native_height = native_height

    def update_geometry(self, parent_wid: int, offset_x: int, offset_y: int,
                        logical_width: int = 0, logical_height: int = 0,
                        native_width: int = 0, native_height: int = 0) -> None:
        self.parent_wid = parent_wid
        self.offset_x = offset_x
        self.offset_y = offset_y
        if logical_width > 0 and logical_height > 0:
            self.logical_width = logical_width
            self.logical_height = logical_height
        if native_width > 0 and native_height > 0:
            self.native_width = native_width
            self.native_height = native_height

    def _draw_packet_target(self, x: int, y: int) -> tuple[int, int, int]:
        return self.parent_wid, x + self.offset_x, y + self.offset_y

    def make_draw_packet(self, x: int, y: int, outw: int, outh: int,
                         coding: str, data, outstride: int, client_options, options):
        logical_w = self.logical_width or self.window.get_dimensions()[0]
        logical_h = self.logical_height or self.window.get_dimensions()[1]
        if x == 0 and y == 0 and logical_w > 0 and logical_h > 0 and (outw, outh) != (logical_w, logical_h):
            if "scaled_size" not in client_options:
                client_options["scaled_size"] = (outw, outh)
            outw, outh = logical_w, logical_h
        return super().make_draw_packet(x, y, outw, outh, coding, data, outstride, client_options, options)

    def schedule_auto_refresh(self, packet, options) -> None:
        # No-op: outbound draw packets carry parent-relative coords (we
        # rewrite wid+offset in `_draw_packet_target`). The base
        # implementation would feed those parent-coord rectangles back
        # through `damage()`, where they'd be clipped against the
        # subsurface's local dimensions and produce garbage refreshes.
        # Re-enable later by translating the region from parent-coords to
        # subsurface-local coords first.
        return
