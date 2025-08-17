
# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from time import monotonic
from typing import Dict, Tuple
from collections.abc import Callable

from xpra.x11.bindings.display_source cimport get_display
from xpra.x11.bindings.events cimport init_x11_events, parse_xevent
from xpra.x11.bindings.xlib cimport (
    Display, Bool, Status, XEvent,
    XFree,
    XPending, XNextEvent, XSync, XFlush,
    XSetErrorHandler, XSetIOErrorHandler, XErrorEvent,
    XAddConnectionWatch, XPointer,
    XInternalConnectionNumbers,
)
from libc.stdint cimport uintptr_t

from xpra.x11.bindings.events import get_x_event_type_name, get_x_event_signals
from xpra.x11.dispatch import route_event
from xpra.x11.error import XError, xsync
from xpra.x11.common import X11Event
from xpra.util.str_fn import csv
from xpra.os_util import gi_import
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("x11", "bindings", "events")


cdef int x11_io_error_handler(Display *display) except 0:
    message = "X11 fatal IO error"
    log.warn(message)
    return 0


last_error: Dict[str, int] = {}


cdef int x11_error_handler(Display *display, XErrorEvent *event) except 0:
    einfo = {
        "serial": event.serial,
        "error": event.error_code,
        "request": event.request_code,
        "minor": event.minor_code,
        "xid": event.resourceid,
    }
    log("x11 error: %s", einfo)
    global last_error
    if not last_error:
        last_error = einfo
    return 0


cdef class EventLoop:

    cdef Display *display

    def __cinit__(self):
        self.display = get_display()
        init_x11_events()
        self.set_x11_error_handlers()

    def set_x11_error_handlers(self) -> None:
        from xpra.x11 import error
        error.Xenter = self.Xenter
        error.Xexit = self.Xexit
        XSetErrorHandler(&x11_error_handler)
        XSetIOErrorHandler(&x11_io_error_handler)

    def process_events(self) -> int:
        log("process_events()")
        cdef XEvent event
        cdef unsigned int count = 0
        while XPending(self.display):
            XNextEvent(self.display, &event)
            self.process_event(&event)
            count += 1
        log("process_events() done %i events", count)
        return count

    cdef void process_event(self, XEvent *event) noexcept:
        cdef int etype = event.type
        ename = get_x_event_type_name(etype) or etype
        event_args = get_x_event_signals(etype)
        if not event_args:
            # not handled
            log("skipped event %r (no handlers)", ename)
            return

        try:
            pyev = parse_xevent(self.display, event)
        except Exception:
            log.error("Error parsing X11 event", exc_info=True)
            return
        log("process_event %s: %s", ename, pyev)
        if not pyev:
            return

        cdef float start = monotonic()
        try:
            signal, parent_signal = event_args
            route_event(etype, pyev, signal, parent_signal)
            log("x_event_filter event=%s/%s took %.1fms", event_args, ename, 1000.0*(monotonic() - start))
        # except (KeyboardInterrupt, SystemExit):
        #    log("exiting on KeyboardInterrupt/SystemExit")
        except:
            log.warn("Unhandled exception in x_event_filter:", exc_info=True)

    def Xenter(self) -> None:
        log("Xenter")

    def Xexit(self, flush=True):
        global last_error
        # log.info("Xexit(%s) last_error=%s", flush, last_error)
        if flush:
            XSync(self.display, False)
            # check for new events in next GLib loop iteration:
            GLib.timeout_add(0, self.process_events)
        else:
            XFlush(self.display)
        if not last_error:
            return None
        err = last_error.get("error", "unknown")
        last_error = {}
        return err


cdef void watch_proc(Display *display, XPointer client_data, int fd, Bool opening, XPointer *watch_data) noexcept:
    log("watch_proc%s", (<uintptr_t> display, client_data, fd, opening, <uintptr_t> watch_data))


def register_glib_source(context) -> None:
    from xpra.x11.bindings.display_source import get_display_ptr
    if not get_display_ptr():
        raise RuntimeError("no display!")
    from xpra.x11.bindings.core import X11CoreBindings
    X11Core = X11CoreBindings()
    cdef uintptr_t display = <uintptr_t> get_display_ptr()
    r = XAddConnectionWatch(<Display *> display, watch_proc, <XPointer> NULL)
    log("XAddConnectionWatch(..)=%s", r)

    cdef int* fd_return
    cdef int count
    cdef Status ret = XInternalConnectionNumbers(<Display *> display, &fd_return, &count)
    log("XInternalConnectionNumbers()=%i", ret)
    if ret:
        log("internal connections: %i", count)
        for i in range(count):
            log(" %i", fd_return[i])
        XFree(fd_return)

    cdef unsigned int fd = X11Core.get_connection_number()
    log("register_glib_source() X11 fd=%i", fd)
    from xpra.os_util import gi_import
    GLib = gi_import("GLib")
    loop = EventLoop()

    def x11_callback(data) -> bool:
        log("x11_callback(%s)", data)
        loop.process_events()
        return True

    def timer(*args):
        loop.process_events()
        return True
    GLib.timeout_add(1000, timer)

    ioc = GLib.IOCondition
    glib_source = GLib.unix_fd_source_new(fd, ioc.IN | ioc.PRI | ioc.HUP | ioc.ERR | ioc.NVAL)
    glib_source.set_name("X11")
    glib_source.set_can_recurse(True)
    glib_source.set_callback(x11_callback, None)
    glib_source.attach(context)
