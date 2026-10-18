# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.server.subsystem.bell import BellServer
from xpra.x11.bindings.core import get_root_xid
from xpra.x11.dispatch import (
    add_event_receiver, remove_event_receiver, add_catchall_receiver, remove_catchall_receiver,
)
from xpra.x11.common import X11Event
from xpra.log import Logger

log = Logger("bell")


class X11BellServer(BellServer):
    """
    X11 servers that forward bell events.

    Bell events are received as `x11-xkb-event` signals from the X11 dispatch.
    By default, we only receive those delivered to the root window:
    bells rung on the windows we manage come through the window models' `bell` signal instead.
    """
    __slots__ = ()
    __signals__ = ("x11-xkb-event", )
    # receive the bell events from all windows, not just the root window:
    CATCHALL = False

    def setup(self) -> None:
        if not self.bell:
            return
        try:
            from xpra.x11.bindings.keyboard import X11KeyboardBindings
            X11Keyboard = X11KeyboardBindings()
        except ImportError as e:
            log.error("Error: unable to listen for bell events:")
            log.estr(e)
            self.bell = False
        else:
            from xpra.x11.error import xlog
            with xlog:
                X11Keyboard.selectBellNotification(True)
            self.connect("x11-xkb-event", self._on_x11_xkb_event)
            if self.CATCHALL:
                add_catchall_receiver("x11-xkb-event", self)
            else:
                add_event_receiver(get_root_xid(), self)

    def cleanup(self) -> None:
        if self.CATCHALL:
            remove_catchall_receiver("x11-xkb-event", self)
        else:
            remove_event_receiver(get_root_xid(), self)

    def _on_x11_xkb_event(self, _emitter, event: X11Event) -> None:
        self.do_x11_xkb_event(event)

    def do_x11_xkb_event(self, event: X11Event) -> None:
        log("server do_x11_xkb_event(%r) bell=%s", event, self.bell)
        if not self.bell:
            return
        # X11: XKBNotify
        if event.subtype != "bell":
            log.error(f"Error: unknown event subtype: {event.subtype!r}")
            log.error(f" {event=}")
            return
        # bell events on our windows will come through the bell signal,
        # this method is a catch-all for events on windows we don't manage,
        # so we use wid=0 for that:
        self.send_bell(0, event.device, event.percent,
                       event.pitch, event.duration, event.bell_class, event.bell_id, event.name)

    def _bell_signaled(self, wm, event) -> None:
        log("bell signaled on window %#x", event.window)
        if not self.bell:
            return
        wid = 0
        rxid = get_root_xid()
        if event.window != rxid and event.window_model is not None:
            if window_manager := self.get_subsystem("window"):
                wid = max(0, window_manager.get_wid(event.window_model))
        log("_bell_signaled(%s,%r) wid=%#x", wm, event, wid)
        self.send_bell(wid, event.device, event.percent,
                       event.pitch, event.duration, event.bell_class, event.bell_id, event.name)


class X11DesktopBellServer(X11BellServer):
    """
    Desktop and monitor servers don't have window models for the applications' windows,
    so we have to catch the bell events from all windows.
    """
    __slots__ = ()
    CATCHALL = True
