# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.x11.bindings.display_source cimport get_display
from xpra.x11.bindings.events cimport add_parser, add_event_type, atom_str
from xpra.x11.bindings.core cimport import_check

from xpra.x11.bindings.xlib cimport (
    Display, Window, Atom, Time, CARD32, Bool,
    XEvent,
    XDefaultRootWindow,
)
from xpra.log import Logger

import_check("xkb")

log = Logger("x11", "bindings", "keyboard")
verbose = Logger("x11", "bindings", "keyboard", "verbose")


cdef extern from "X11/extensions/XKB.h":
    unsigned int XkbUseCoreKbd
    unsigned int XkbBellNotifyMask
    unsigned int XkbBellNotify

    ctypedef struct XkbAnyEvent:
        unsigned long   serial
        Bool            send_event
        Display *       display
        Time            time
        int             xkb_type
        unsigned int    device


cdef extern from "X11/XKBlib.h":
    Bool XkbQueryExtension(Display *, int *opcodeReturn, int *event_base, int *error_base, int *major, int *minor)


cdef extern from "X11/extensions/XKBproto.h":
    ctypedef struct XkbBellNotifyEvent:
        int          type
        CARD32       serial
        Bool         send_event
        Display*     display
        Time         time
        int          xkb_type
        unsigned int device
        int          percent
        int          pitch
        int          duration
        unsigned int bell_class
        unsigned int bell_id
        Atom         name
        Window       window
        Bool         event_only


cdef unsigned int init_done = 0
cdef int event_base = 0
cdef int error_base = 0


def init_xkb_events() -> bool:
    global init_done
    if init_done:
        return event_base > 0
    init_done = 1
    cdef Display *display = get_display()
    cdef int opcode = 0
    cdef int major = 0
    cdef int minor = 0
    if not XkbQueryExtension(display, &opcode, &event_base, &error_base, &major, &minor):
        log.warn("Warning: Xkb extension is not available")
        return False
    if event_base <= 0:
        log.warn("Warning: Xkb extension returned invalid event base: %d", event_base)
        return False
    cdef int XKBNotify = event_base
    log("XKBNotify=%d", XKBNotify)
    add_event_type(XKBNotify, "XKBNotify", "x11-xkb-event", "")
    add_parser(XKBNotify, parse_XKBNotify)
    return True


cdef dict parse_XKBNotify(Display *d, XEvent *e):
    cdef XkbAnyEvent * xkb_e = <XkbAnyEvent*> e
    # note we could just cast directly to XkbBellNotifyEvent
    # but this would be dirty, and we may want to catch
    # other types of XKB events in the future
    verbose("XKBNotify event received xkb_type=%s", xkb_e.xkb_type)
    if xkb_e.xkb_type != XkbBellNotify:
        return {}
    bell_e = <XkbBellNotifyEvent*>e
    # no idea why window is not set in XkbBellNotifyEvent
    # since we can fire it from a specific window
    # but we need one for the dispatch logic, so use root if unset
    cdef Window window = bell_e.window
    if not window:
        window = XDefaultRootWindow(d)
        verbose("bell using root window=%#x", window)
    return {
        "window": window,
        "delivered_to": window,
        "subtype": "bell",
        "device": int(bell_e.device),
        "percent": int(bell_e.percent),
        "pitch": int(bell_e.pitch),
        "duration": int(bell_e.duration),
        "bell_class": int(bell_e.bell_class),
        "bell_id": int(bell_e.bell_id),
        "event_only": bool(bell_e.event_only),
        "name": atom_str(d, bell_e.name),
        "window_model": None,
    }
