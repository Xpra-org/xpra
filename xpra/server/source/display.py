# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Sequence

from xpra.util.objects import typedict
from xpra.util.rectangle import rectangle
from xpra.util.screen import MonitorLayout
from xpra.net.packet_type import DISPLAY_RESIZED, DISPLAY_SHOW_DESKTOP
from xpra.util.parsing import validated_monitor_data
from xpra.server.source.stub import StubClientConnection, is_recording_allowed
from xpra.log import Logger

log = Logger("display")
sharinglog = Logger("sharing")


class DisplayConnection(StubClientConnection):
    """
    Store information and manage events related to the client's display
    """
    PREFIX = "display"

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:
        # v7 command clients (ie: `xpra top :N`) may send the display name as a string,
        # they don't have a display:
        return isinstance(caps.get(DisplayConnection.PREFIX), dict)

    def cleanup(self) -> None:
        self.init_state()

    def init_state(self) -> None:
        self.vrefresh: int = -1
        self.icc: dict = {}
        self.display_icc: dict = {}
        self.desktop_size: tuple[int, int] = (0, 0)
        self.desktop_mode_size: tuple[int, int] = (0, 0)
        self.desktop_size_unscaled: tuple[int, int] = (0, 0)
        self.desktop_size_server: tuple[int, int] = (0, 0)
        self.desktop_fullscreen: bool = False
        self.monitors: dict[int, Any] = {}
        self.monitor_layout = MonitorLayout()
        # does this client attach a `monitor` descriptor to its window and pointer packets?
        # (required for `sharing=combine`, assumed when we don't support older clients)
        self.monitor_relative = True
        # the area of the server's virtual display that belongs to this client,
        # only used by `sharing=combine` - `None` means the whole display:
        self.display_area: rectangle | None = None
        self.desktops: int = 1
        self.desktop_names: Sequence[str] = ()
        self.show_desktop_allowed: bool = False
        self.opengl_props: dict[str, Any] = {}
        self.display_record = False
        self.resize_events = True

    def get_info(self) -> dict[str, Any]:
        info = {
            "vertical-refresh": self.vrefresh,
            "desktop_size": self.desktop_size if self.desktop_size != (0, 0) else "",
            "desktops": self.desktops,
            "desktop_names": self.desktop_names,
            "opengl": self.opengl_props,
            "monitors": self.monitors,
            "monitor-relative": self.monitor_relative,
        }
        if area := self.display_area:
            info["area"] = (area.x, area.y, area.width, area.height)
        if self.desktop_mode_size != (0, 0):
            info["desktop_mode_size"] = self.desktop_mode_size
        if self.desktop_size_unscaled != (0, 0):
            info["desktop_size"] = {"unscaled": self.desktop_size_unscaled}
        return info

    def requires_sharing(self) -> bool:
        return not self.display_record

    def parse_client_caps(self, c: typedict) -> None:
        display_caps = c.dictget("display")
        if not display_caps:
            raise ValueError("missing display capabilities")
        c = typedict(display_caps)
        self.resize_events = c.boolget("resize-events", True)
        self.vrefresh = c.intget("refresh-rate", -1)
        self.desktop_size = c.intpair("desktop_size")
        if self.desktop_size != (0, 0):
            w, h = self.desktop_size
            if w <= 0 or h <= 0 or w >= 32768 or h >= 32768:
                log.warn("ignoring invalid desktop dimensions: %sx%s", w, h)
                self.desktop_size = (0, 0)
        self.desktop_mode_size = c.intpair("desktop_mode_size")
        self.desktop_size_unscaled = c.intpair("desktop_size.unscaled")
        self.desktop_fullscreen = c.boolget("desktop-fullscreen")
        self.set_monitors(c.dictget("monitors"))
        self.monitor_relative = c.boolget("monitor-relative", True)
        desktop_names = tuple(str(x) for x in c.tupleget("desktop.names"))
        self.set_desktops(c.intget("desktops", 1), desktop_names)
        self.show_desktop_allowed = c.boolget("show-desktop")
        self.icc = c.dictget("icc")
        self.display_icc = c.dictget("display-icc")
        self.opengl_props = c.dictget("opengl")
        self.display_record = c.boolget("record", False) and is_recording_allowed(self, "display")

    def set_monitors(self, monitors: dict[int, dict]) -> None:
        self.monitors = validated_monitor_data(monitors)
        self.monitor_layout = MonitorLayout(self.monitors)
        log("set_monitors(%s) monitors=%s", monitors, self.monitors)

    def set_display_area(self, area: rectangle | None) -> None:
        """ which part of the server's virtual display this client occupies (`sharing=combine`) """
        sharinglog("set_display_area(%s) was %s", area, self.display_area)
        self.display_area = area

    def get_display_origin(self) -> tuple[int, int]:
        """ where this client's display area starts on the server's virtual display """
        if area := self.display_area:
            return area.x, area.y
        return 0, 0

    def get_display_area_size(self) -> tuple[int, ...]:
        """ the size of the display as this client sees it,
            empty unless this client has been given an area of its own """
        if area := self.display_area:
            return area.width, area.height
        return ()

    def get_monitor_position(self, index: int, position: Sequence[int], normalized: bool = True) -> tuple[int, int] | None:
        if len(position) != 2:
            return None
        pos = self.monitor_layout.position(index, int(position[0]), int(position[1]), normalized)
        if pos is None:
            return None
        # the client's monitor layout is placed at the origin of its display area:
        ox, oy = self.get_display_origin()
        return pos[0] + ox, pos[1] + oy

    def set_desktops(self, desktops: int, desktop_names) -> None:
        self.desktops = desktops or 1
        self.desktop_names = tuple(str(d) for d in (desktop_names or ()))

    def updated_desktop_size(self, root_w: int, root_h: int, max_w: int, max_h: int) -> bool:
        log("updated_desktop_size%s desktop_size=%s", (root_w, root_h, max_w, max_h), self.desktop_size)
        if not self.hello_sent or not self.resize_events:
            return False
        if area_size := self.get_display_area_size():
            # this client only sees its own area of the virtual display:
            sharinglog("updated_desktop_size: %s only sees its %s area", self, area_size)
            root_w, root_h = area_size
            max_w, max_h = area_size
        if self.desktop_size_server != (root_w, root_h):
            self.desktop_size_server = root_w, root_h
            self.send(DISPLAY_RESIZED, root_w, root_h, max_w, max_h)
            return True
        return False

    def show_desktop(self, show) -> None:
        if self.show_desktop_allowed and self.hello_sent:
            self.send_async(DISPLAY_SHOW_DESKTOP, show)

    def get_monitor_definitions(self) -> dict[int, Any] | None:
        return self.monitors or {}

    def get_normalized_monitor_definitions(self) -> dict[int, Any] | None:
        monitors = self.get_monitor_definitions()
        if not monitors:
            return monitors
        layout = self.monitor_layout if self.monitors else MonitorLayout(monitors)
        return layout.normalized_monitors(monitors)

    def get_client_workarea(self):
        """ the usable area of the client's display (excluding panels / taskbars), as a single rectangle:
            the bounding box of the per-monitor workareas (the `monitors` dict) """
        rects = []
        for mdef in (self.monitors or {}).values():
            wa = mdef.get("workarea")
            if wa and len(wa) == 4 and wa[2] > 0 and wa[3] > 0:
                rects.append(wa)
        if not rects:
            return None
        x = min(r[0] for r in rects)
        y = min(r[1] for r in rects)
        w = max(r[0] + r[2] for r in rects) - x
        h = max(r[1] + r[3] for r in rects) - y
        return rectangle(x, y, w, h)

    def get_client_workareas(self) -> list[tuple[int, int, int, int]]:
        """ the usable area of each of the client's monitors, in the normalized coordinate space
            used for the monitor geometries - this is what `_GTK_WORKAREAS_D#` expects.
            Empty if the client did not provide any. """
        rects = []
        for mdef in (self.get_normalized_monitor_definitions() or {}).values():
            wa = mdef.get("workarea")
            if wa and len(wa) == 4 and wa[2] > 0 and wa[3] > 0:
                rects.append(tuple(wa))
        return rects
