# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Deque
from collections.abc import Callable
from time import monotonic
from collections import deque

from xpra.common import noop
from xpra.platform.paths import get_icon_filename
from xpra.log import Logger

log = Logger("tray")


class TrayBase:
    """
        Utility superclass for all tray implementations
    """

    def __init__(self, _client, app_id, menu, tooltip: str = "", icon_filename: str = "",
                 size_changed_cb: Callable = noop, click_cb: Callable = noop,
                 mouseover_cb: Callable = noop, exit_cb: Callable = noop):
        # we don't keep a reference to client,
        # because calling functions on the client directly should be discouraged
        self.app_id = app_id
        self.menu = menu
        self.tooltip = tooltip
        self.size_changed_cb = size_changed_cb
        self.click_cb = click_cb
        self.mouseover_cb = mouseover_cb
        self.exit_cb = exit_cb
        self.tray_widget = None
        self.default_icon_filename = icon_filename  # ie: "xpra" or "/path/to/xpra.png"
        # some implementations need this for guessing the geometry (see recalculate_geometry):
        self.geometry_guess: tuple[int, int, int, int] | None = None
        self.tray_event_locations: Deque[tuple[int, int]] = deque(maxlen=512)
        self.default_icon_extension = "png"
        self.icon_timestamp = 0.0

    def __repr__(self):
        return f"Tray({self.app_id}:{self.tooltip})"

    def cleanup(self) -> None:
        if self.tray_widget:
            self.hide()
            self.tray_widget = None

    def ready(self) -> None:
        """
        This is called when we have finished the startup sequence.
        The MacOS dock overrides this method.
        """

    def show(self) -> None:
        raise NotImplementedError

    def hide(self) -> None:
        raise NotImplementedError

    def get_orientation(self) -> str:
        return ""  # assume "HORIZONTAL"

    def get_geometry(self) -> tuple[int, int, int, int]:
        raise NotImplementedError

    def get_size(self) -> tuple[int, int] | None:
        g = self.get_geometry()
        if not g:
            return None
        return g[2], g[3]

    def set_tooltip(self, tooltip: str = "") -> None:
        self.tooltip = tooltip
        raise NotImplementedError

    def set_blinking(self, on: bool) -> None:
        raise NotImplementedError

    def set_icon_from_data(self, pixels, has_alpha: bool, w: int, h: int, rowstride: int, options=None):
        raise NotImplementedError

    def get_icon_filename(self, basename="") -> str:
        name = basename or self.default_icon_filename
        f = get_icon_filename(name, self.default_icon_extension)
        if not f:
            log.error(f"Error: cannot find icon {name!r}")
        return f

    def set_icon(self, basename="") -> None:
        filename = self.get_icon_filename(basename)
        if not filename:
            return
        log(f"set_icon({basename}) using filename={filename!r}")
        self.set_icon_from_file(filename)

    def set_icon_from_file(self, filename: str) -> None:
        log(f"set_icon_from_file({filename}) tray_widget={self.tray_widget}")
        if not self.tray_widget:
            return
        self.do_set_icon_from_file(filename)
        self.icon_timestamp = monotonic()

    def do_set_icon_from_file(self, filename: str) -> None:
        raise NotImplementedError

    def recalculate_geometry(self, x: int, y: int, width: int, height: int) -> None:
        log("recalculate_geometry%s guess=%s, tray event locations: %s",
            (x, y, width, height), self.geometry_guess, len(self.tray_event_locations))
        if x is None or y is None:
            return
        if self.geometry_guess is None:
            # better than nothing!
            self.geometry_guess = x, y, width, height
        if self.tray_event_locations and self.tray_event_locations[-1] == (x, y):
            # unchanged
            log("tray event location unchanged")
            return
        self.tray_event_locations.append((x, y))
        # sets of locations that can fit together within (size,size) distance of each other:
        xs, ys = set(), set()
        xs.add(x)
        ys.add(y)
        # walk through all of them in reverse (and stop when one does not fit):
        for tx, ty in reversed(self.tray_event_locations):
            minx = min(xs)
            miny = min(ys)
            maxx = max(xs)
            maxy = max(ys)
            if (tx < minx and tx < (maxx - width)) or (tx > maxx and tx > (minx + width)):
                break  # cannot fit...
            if (ty < miny and ty < (maxy - height)) or (ty > maxy and ty > (miny + height)):
                break  # cannot fit...
            xs.add(tx)
            ys.add(ty)
        # now add some padding if needed:
        minx = min(xs)
        miny = min(ys)
        maxx = max(xs)
        maxy = max(ys)
        padx = width - (maxx - minx)
        pady = height - (maxy - miny)
        assert padx >= 0 and pady >= 0
        minx -= padx // 2
        miny -= pady // 2
        oldgeom = self.geometry_guess
        self.geometry_guess = max(0, minx), max(0, miny), width, height
        log("recalculate_geometry() geometry guess=%s (old guess=%s)", self.geometry_guess, oldgeom)
        if self.geometry_guess != oldgeom:
            self.size_changed_cb()
