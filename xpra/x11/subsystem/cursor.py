# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Sequence, Callable

from xpra.server.subsystem.cursor import CursorManager
from xpra.util.str_fn import Ellipsizer
from xpra.x11.dispatch import add_event_receiver
from xpra.x11.common import X11Event
from xpra.x11.error import xlog
from xpra.common import noop
from xpra.log import Logger

log = Logger("x11", "server", "cursor")


class XCursorServer(CursorManager):
    __signals__ = {
        "x11-cursor-event": 1,
    }

    def __init__(self):
        CursorManager.__init__(self)
        self.last_cursor_serial = 0

    def setup(self) -> None:
        log("setup() cursors=%s", self.cursors)
        if not self.cursors:
            return
        with xlog:
            try:
                from xpra.x11.bindings.fixes import XFixesBindings, init_xfixes_events
                init_xfixes_events()
                XFixes = XFixesBindings()
                fixes = XFixes.hasXFixes()
            except ImportError:
                fixes = False
            log("setup() fixes=%s", fixes)
            if not fixes and self.cursors:
                log.error("Error: cursor forwarding support is not available")
                self.cursors = False
                return
            XFixes.selectCursorChange(True)
            self.default_cursor_image = XFixes.get_cursor_image()
            log("get_default_cursor=%s", Ellipsizer(self.default_cursor_image))
            from xpra.x11.bindings.core import get_root_xid
            rxid = get_root_xid()
            add_event_receiver(rxid, self)

    # noinspection PyMethodMayBeStatic
    def get_cursor_image(self) -> Sequence:
        if not self.cursors:
            return ()
        # must be called from the UI thread!
        with xlog:
            from xpra.x11.bindings.fixes import XFixesBindings
            return XFixesBindings().get_cursor_image()

    def get_cursor_data(self, skip_default=True) -> tuple[Any, Any]:
        # must be called from the UI thread!
        if not self.cursors:
            return None, []
        cursor_image = self.get_cursor_image()
        if cursor_image is None:
            log("get_cursor_data() failed to get cursor image")
            return None, []
        self.last_cursor_image = list(cursor_image)
        pixels = self.last_cursor_image[7]
        log("get_cursor_image() cursor=%s", cursor_image[:7] + ["%s bytes" % len(pixels)] + cursor_image[8:])
        is_default = self.default_cursor_image is not None and str(pixels) == str(self.default_cursor_image[7])
        if skip_default and is_default:
            log("get_cursor_data(): default cursor - clearing it")
            cursor_image = None
        try:
            from xpra.x11.bindings.cursor import X11CursorBindings
            size = X11CursorBindings().get_default_cursor_size()
        except ImportError as e:
            size = 32
            from xpra.util.env import first_time
            if first_time("x11-cursor"):
                log.warn("Warning: missing X11 cursor bindings")
                log.warn(" %s", e)
                log.warn(" using default cursor size %i", size)
        return cursor_image, (size, (32767, 32767))

    def do_x11_cursor_event(self, event: X11Event) -> None:
        if not self.cursors:
            return
        if self.last_cursor_serial == event.cursor_serial:
            log("ignoring cursor event %s with the same serial number %s", event, self.last_cursor_serial)
            return
        log("cursor_event: %s", event)
        self.last_cursor_serial = event.cursor_serial
        for ss in self.window_sources():
            # not all client connections support `send_cursor`:
            send_cursor: Callable = getattr(ss, "send_cursor", noop)
            send_cursor()
