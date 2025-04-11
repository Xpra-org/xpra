# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.server.source.stub_source_mixin import StubSourceMixin
from xpra.util.objects import typedict
from xpra.log import Logger

log = Logger("keyboard")


class PointerMixin(StubSourceMixin):
    """
    Manage pointer devices (mouse, etc)
    """

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:
        return caps.boolget("mouse")

    def init_state(self) -> None:
        self.double_click_time: int = -1
        self.double_click_distance: tuple[int, int] | None = None
        # mouse echo:
        self.mouse_last_position: tuple[int, int] | None = None
        self.mouse_last_relative_position: tuple[int, int] | None = None

    def parse_client_caps(self, c: typedict) -> None:
        dc = c.dictget("double_click")
        if dc:
            dc = typedict(dc)
            self.double_click_time = dc.intget("time")
            self.double_click_distance = dc.intpair("distance")
        else:
            self.double_click_time = c.intget("double_click.time")
            self.double_click_distance = c.intpair("double_click.distance")
        self.mouse_last_position = c.intpair("mouse.initial-position")

    def get_info(self) -> dict[str, Any]:
        dc_info: dict[str, Any] = {}
        dct = self.double_click_time
        if dct:
            dc_info["time"] = dct
        dcd = self.double_click_distance
        if dcd:
            dc_info["distance"] = dcd
        info = {}
        if dc_info:
            info["double-click"] = dc_info
        return info

    def update_mouse(self, wid: int, x: int, y: int, rx: int, ry: int) -> None:
        log("update_mouse(%s, %i, %i, %i, %i) current=%s, client=%i",
            wid, x, y, rx, ry, self.mouse_last_position, self.counter)
        if self.mouse_last_position != (x, y) or self.mouse_last_relative_position != (rx, ry):
            self.mouse_last_position = (x, y)
            self.mouse_last_position = (rx, ry)
            self.send_async("pointer-position", wid, x, y, rx, ry)
