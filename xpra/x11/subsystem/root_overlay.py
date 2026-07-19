# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.server.common import get_sources_by_type
from xpra.server.subsystem.stub import StubSubsystem
from xpra.x11.bindings.window import X11WindowBindings
from xpra.x11.error import xsync
from xpra.log import Logger

log = Logger("screen")


def rindex(alist: list | tuple, avalue: Any) -> int:
    return len(alist) - alist[::-1].index(avalue) - 1


class RootOverlay(StubSubsystem):
    """
    Mirrors seamless window content into the XComposite root overlay.
    """
    PREFIX = "root-overlay"

    def __init__(self, server=None):
        super().__init__(server)
        self.root_overlay = 0
        self.repaint_timer = 0
        self.sync_xvfb = 0

    def init(self, opts) -> None:
        self.sync_xvfb = int(opts.sync_xvfb or 0)

    def setup(self) -> None:
        if self.sync_xvfb <= 0:
            return
        try:
            from xpra.x11.server.root_overlay import init_root_overlay
            self.root_overlay = init_root_overlay()
        except ImportError as e:
            log("init_root_overlay()", exc_info=True)
            log.error("Error setting up xvfb synchronization:")
            log.estr(e)

    def cleanup(self) -> None:
        self.cancel_repaint()
        if ro := self.root_overlay:
            self.root_overlay = 0
            from xpra.x11.server.root_overlay import release_root_overlay
            release_root_overlay(ro)

    def is_overlay_window(self, xid: int) -> bool:
        return bool(self.root_overlay and self.root_overlay == xid)

    def repaint(self) -> None:
        if not self.root_overlay:
            return
        log("repaint() root_overlay=%s, due=%s, sync-xvfb=%ims",
            self.root_overlay, self.repaint_timer, self.sync_xvfb)
        if self.repaint_timer:
            return
        self.repaint_timer = self.timeout_add(self.sync_xvfb, self.do_repaint)

    def cancel_repaint(self) -> None:
        if timer := self.repaint_timer:
            self.repaint_timer = 0
            self.source_remove(timer)

    def do_repaint(self) -> None:
        self.repaint_timer = 0
        if not self.root_overlay:
            return
        with xsync:
            root_width, root_height = X11WindowBindings().get_root_size()
        import cairo
        from xpra.cairo.context import xlib_surface_create
        from xpra.x11.server.root_overlay import fill_rect
        surface = xlib_surface_create(self.root_overlay)
        cr = cairo.Context(surface)
        fill_rect(cr, (0, 0, 0), 0, 0, root_width, root_height)
        self.paint_monitors(cr)
        self.paint_windows(cr)

    def paint_monitors(self, cr) -> None:
        try:
            from xpra.server.source.display import DisplayConnection
        except ImportError:
            return
        display_sources = get_sources_by_type(self.server, DisplayConnection)
        if len(display_sources) != 1:
            return
        ss = display_sources[0]
        if ss.screen_sizes and len(ss.screen_sizes) == 1:
            from xpra.x11.server.root_overlay import paint_overlay_monitors
            paint_overlay_monitors(cr, ss.screen_sizes[0])

    def paint_windows(self, cr) -> bool:
        order = {}
        window_sub = self.get_subsystem("window")
        if not window_sub:
            return False
        focus_history = tuple(window_sub._focus_history)
        for window in window_sub.models():
            wid = window_sub.get_wid(window)
            prio = int(window_sub._has_focus == wid) * 32768 + int(window_sub._has_grab == wid) * 65536
            if prio == 0:
                try:
                    prio = rindex(focus_history, wid)
                except ValueError:
                    pass
            order[(prio, wid)] = window
        from xpra.x11.server.root_overlay import paint_root_overlay_windows, paint_overlay_pointer
        paint_root_overlay_windows(cr, [order[key] for key in sorted(order)])
        try:
            from xpra.server.source.pointer import PointerConnection
        except ImportError:
            sources = ()
        else:
            sources = get_sources_by_type(self.server, PointerConnection)
        if len(sources) == 1:
            mlp = getattr(sources[0], "mouse_last_position", (0, 0))
            if mlp != (0, 0):
                paint_overlay_pointer(cr, *mlp[:2])
        return False

    def update_window(self, window, x: int, y: int, width: int, height: int) -> None:
        if not self.root_overlay:
            return
        image = window.get_image(x, y, width, height)
        if image:
            from xpra.x11.server.root_overlay import update_root_overlay
            update_root_overlay(self.root_overlay, window, x, y, image)
