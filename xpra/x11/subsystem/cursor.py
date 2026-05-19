# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Sequence, Callable

from xpra.server.subsystem.cursor import CursorManager
from xpra.util.str_fn import Ellipsizer
from xpra.x11.dispatch import add_event_receiver
from xpra.x11.common import X11Event, get_default_cursor_size
from xpra.x11.error import xlog
from xpra.common import noop
from xpra.log import Logger

log = Logger("x11", "server", "cursor")


class XCursorServer(CursorManager):
    """
    X11 cursor subsystem - forwards cursor changes via XFixes.

    The `x11-cursor-event` signal is declared on each X11 server class's
    `__gsignals__` (seamless, desktop, monitor, X11 shadow). It is *not*
    declared on this subsystem because the X11 dispatch
    (`xpra.x11.dispatch._maybe_send_event`) calls `signal_list_names` on
    each receiver and only accepts a GObject - `XCursorServer` is a plain
    Python object. This subsystem consumes the signal via
    `self.server.connect("x11-cursor-event", ...)`.
    """

    def __init__(self, server=None):
        CursorManager.__init__(self, server)
        self.last_cursor_serial = 0

    def setup(self) -> None:
        log("setup() cursors=%s", self.enabled)
        if not self.enabled:
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
            if not fixes and self.enabled:
                log.error("Error: cursor forwarding support is not available")
                self.enabled = False
                return
            XFixes.selectCursorChange(True)
            self.default_image = XFixes.get_cursor_image()
            log("get_default_cursor=%s", Ellipsizer(self.default_image))
            from xpra.x11.bindings.core import get_root_xid
            rxid = get_root_xid()
            # register the GObject server as the receiver (X11 dispatch
            # requires a GObject type, see BellServer.setup for context)
            # and route the signal to our subsystem method:
            add_event_receiver(rxid, self.server)
            self.server.connect("x11-cursor-event", self._on_x11_cursor_event)

    def _on_x11_cursor_event(self, _emitter, event: X11Event) -> None:
        self.do_x11_cursor_event(event)

    # noinspection PyMethodMayBeStatic
    def get_cursor_image(self) -> Sequence:
        if not self.enabled:
            return ()
        # must be called from the UI thread!
        with xlog:
            from xpra.x11.bindings.fixes import XFixesBindings
            return XFixesBindings().get_cursor_image()

    def get_cursor_data(self, skip_default=True) -> tuple[Any, Any]:
        # must be called from the UI thread!
        if not self.enabled:
            return None, []
        cursor_image = self.get_cursor_image()
        if cursor_image is None:
            log("get_cursor_data() failed to get cursor image")
            return None, []
        self.last_image = list(cursor_image)
        pixels = self.last_image[7]
        log("get_cursor_image() cursor=%s", cursor_image[:7] + ["%s bytes" % len(pixels)] + cursor_image[8:])
        is_default = self.default_image is not None and str(pixels) == str(self.default_image[7])
        if skip_default and is_default:
            log("get_cursor_data(): default cursor - clearing it")
            cursor_image = None
        size = get_default_cursor_size()
        return cursor_image, (size, (32767, 32767))

    def do_x11_cursor_event(self, event: X11Event) -> None:
        if not self.enabled:
            return
        if self.last_cursor_serial == event.cursor_serial:
            log("ignoring cursor event %s with the same serial number %s", event, self.last_cursor_serial)
            return
        log("cursor_event: %s", event)
        self.last_cursor_serial = event.cursor_serial
        for ss in self.server.window_sources():
            # not all client connections support `send_cursor`:
            send_cursor: Callable = getattr(ss, "send_cursor", noop)
            send_cursor()
