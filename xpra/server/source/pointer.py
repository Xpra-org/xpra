# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.common import BACKWARDS_COMPATIBLE
from xpra.server.source.stub import StubClientConnection
from xpra.util.objects import typedict
from xpra.log import Logger

log = Logger("pointer")


class PointerConnection(StubClientConnection):
    """
    Manage pointer devices (mouse, etc)
    """

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:
        if caps.boolget("pointer"):
            return True
        return BACKWARDS_COMPATIBLE and (caps.boolget("mouse") or caps.boolget("mouse.show"))

    def init_state(self) -> None:
        self.double_click_time: int = -1
        self.double_click_distance: tuple[int, int] | None = None
        # mouse echo:
        self.mouse_last_position: tuple[int, int] | None = None
        self.mouse_last_relative_position: tuple[int, int] | None = None

    def parse_client_caps(self, c: typedict) -> None:
        pointer = typedict(c.dictget("pointer", {}))
        log(f"parse_client_caps(..) {pointer=}")
        dc = typedict(pointer.dictget("double_click", {}))
        if not BACKWARDS_COMPATIBLE:
            self.double_click_time = dc.intget("time", -1)
            self.double_click_distance = dc.intpair("distance", (-1, -1))
            self.mouse_last_position = pointer.intpair("initial-position")
        else:
            # try top-level:
            dc = typedict(c.dictget("double_click", {}))
            if dc:
                self.double_click_time = dc.intget("time", -1)
                self.double_click_distance = dc.intpair("distance")
            else:
                self.double_click_time = c.intget("double_click.time", -1)
                self.double_click_distance = c.intpair("double_click.distance", (-1, -1))
            self.mouse_last_position = c.intpair("mouse.initial-position")
        log("parse_client_caps(..) double-click=%s, position=%s",
            (self.double_click_time, self.double_click_distance), self.mouse_last_position)

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
