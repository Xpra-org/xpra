
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
from cpython.ref cimport PyObject, Py_INCREF, Py_DECREF

cdef extern from "glib.h":
    ctypedef int gint
    ctypedef int gboolean
    ctypedef void* gpointer
    ctypedef unsigned int guint
    ctypedef unsigned short gushort

    ctypedef struct GSource:
        pass

    ctypedef gboolean (*GSourceFunc)(gpointer user_data) noexcept

    ctypedef struct GSourceFuncs:
        gboolean (*prepare)  (GSource *source, gint *timeout_) noexcept
        gboolean (*check)    (GSource *source) noexcept
        gboolean (*dispatch) (GSource *source, GSourceFunc callback, gpointer user_data) noexcept
        void     (*finalize) (GSource *source)

    ctypedef struct GMainContext:
        pass

    ctypedef struct GPollFD:
        int      fd
        gushort  events
        gushort  revents

    GSource         *g_source_new(GSourceFuncs *source_funcs, guint struct_size) nogil
    void             g_source_add_poll(GSource *source, GPollFD *fd) nogil
    guint            g_source_attach(GSource *source, GMainContext *context) nogil
    void             g_source_unref(GSource *source) nogil
    GMainContext    *g_main_context_default() nogil
    guint            g_timeout_add(guint interval, GSourceFunc function, gpointer data) nogil

    int G_IO_IN
    int G_IO_PRI
    int G_IO_HUP
    int G_IO_ERR
    int G_IO_NVAL
    gboolean G_SOURCE_CONTINUE

from xpra.x11.bindings.events import get_x_event_type_name, get_x_event_signals
from xpra.x11.dispatch import route_event
from xpra.x11.error import XError, xsync
from xpra.x11.common import X11Event
from xpra.util.env import envint
from xpra.util.str_fn import csv
from xpra.os_util import gi_import
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("x11", "bindings", "events")

POLL_DELAY = envint("XPRA_X11_POLL_DELAY", 100)


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

    cdef gboolean poll(self) noexcept nogil:
        # called without the GIL: only acquire it if there is work to do
        if XPending(self.display) <= 0:
            return G_SOURCE_CONTINUE
        with gil:
            self.process_events()
        return G_SOURCE_CONTINUE

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

        cdef double start = monotonic()
        try:
            signal, parent_signal = event_args
            route_event(etype, pyev, signal, parent_signal)
            log("x_event_filter event=%s/%s took %.1fms", event_args, ename, 1000.0 * (monotonic() - start))
        # except (KeyboardInterrupt, SystemExit):
        #    log("exiting on KeyboardInterrupt/SystemExit")
        except:
            log.warn("Unhandled exception in x_event_filter:", exc_info=True)

    def Xenter(self) -> None:
        log("Xenter")

    def Xexit(self, flush=True):
        global last_error
        log("Xexit(%s) last_error=%s", flush, last_error)
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


# Custom GLib source that wakes up both when the X11 fd has data (via GPollFD)
# and when Xlib has already buffered events (via prepare/check calling XPending).
# This avoids the need for a periodic timer to catch events that Xlib read
# ahead (e.g. during XSync) before GLib could observe the fd becoming readable.

cdef struct X11GSource:
    GSource   base
    Display  *display
    GPollFD   poll_fd
    PyObject *loop   # owned reference to the Python EventLoop

cdef GSourceFuncs x11_source_funcs

cdef gboolean x11_source_prepare(GSource *source, gint *timeout) noexcept nogil:
    timeout[0] = -1   # no timeout: fd poll or XPending will wake us
    return XPending((<X11GSource *> source).display) > 0

cdef gboolean x11_source_check(GSource *source) noexcept nogil:
    cdef X11GSource *s = <X11GSource *> source
    return s.poll_fd.revents != 0 or XPending(s.display) > 0

cdef gboolean x11_source_dispatch(GSource *source, GSourceFunc callback, gpointer user_data) noexcept nogil:
    cdef X11GSource *s = <X11GSource *> source
    with gil:
        (<object> s.loop).process_events()
    return G_SOURCE_CONTINUE

cdef void x11_source_finalize(GSource *source) noexcept nogil:
    cdef X11GSource *s = <X11GSource *> source
    if s.loop:
        s.loop = NULL

x11_source_funcs.prepare  = x11_source_prepare
x11_source_funcs.check    = x11_source_check
x11_source_funcs.dispatch = x11_source_dispatch
x11_source_funcs.finalize = x11_source_finalize


loop = None


cdef gboolean x11_poll_timeout(gpointer user_data) noexcept nogil:
    return (<EventLoop> user_data).poll()


def register_glib_source(context) -> None:
    global loop
    from xpra.x11.bindings.display_source import get_display_ptr
    if not get_display_ptr():
        raise RuntimeError("no display!")
    from xpra.x11.bindings.core import X11CoreBindings
    X11Core = X11CoreBindings()
    cdef uintptr_t display_ptr = <uintptr_t> get_display_ptr()
    r = XAddConnectionWatch(<Display *> display_ptr, watch_proc, <XPointer> NULL)
    log("XAddConnectionWatch(..)=%s", r)

    cdef int* fd_return
    cdef int count
    cdef Status ret = XInternalConnectionNumbers(<Display *> display_ptr, &fd_return, &count)
    log("XInternalConnectionNumbers()=%i", ret)
    if ret:
        log("internal connections: %i", count)
        for i in range(count):
            log(" %i", fd_return[i])
        XFree(fd_return)

    cdef unsigned int fd = X11Core.get_connection_number()
    log("register_glib_source() X11 fd=%i", fd)

    loop = EventLoop()

    cdef X11GSource *source = <X11GSource *> g_source_new(&x11_source_funcs, sizeof(X11GSource))
    source.display = <Display *> display_ptr
    source.poll_fd.fd = fd
    source.poll_fd.events = G_IO_IN | G_IO_PRI | G_IO_HUP | G_IO_ERR | G_IO_NVAL
    source.loop = <PyObject *> loop
    g_source_add_poll(<GSource *> source, &source.poll_fd)
    g_source_attach(<GSource *> source, g_main_context_default())
    g_source_unref(<GSource *> source)
    # fallback: poll periodically in case events still go missing
    if POLL_DELAY > 0:
        g_timeout_add(POLL_DELAY, x11_poll_timeout, <gpointer> loop)
    log("register_glib_source() done, source attached")
