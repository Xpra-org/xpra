# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from __future__ import absolute_import

import os

import gobject
import gtk
import gtk.gdk

from libc.stdint cimport uintptr_t

from xpra.log import Logger
log = Logger("osx", "bindings", "gtk")


cdef extern from "Cocoa/Cocoa.h":
    ctypedef int NSEventType
    int NSScrollWheel
    ctypedef struct NSEvent:
        pass

cdef extern from "nsevent_glue.h":
    #couldn't figure out how to get unions and cython+objc to play nice,
    #so we use a wrapper:
    NSEventType getNSEventType(NSEvent *nsevent)
    double getNSEventScrollingDeltaX(NSEvent *nsevent)
    double getNSEventScrollingDeltaY(NSEvent *nsevent)
    int getPreciseScrollingDeltas(NSEvent *nsevent)
    void *getNSEventView(NSEvent *nsevent)
    int getNSEventMouseLocationX(NSEvent *nsevent)
    int getNSEventMouseLocationY(NSEvent *nsevent)

cdef extern from "gdk/gdk.h":
    pass

# Serious black magic happens here (I owe these guys beers):
cdef extern from "pygobject.h":
    void pygobject_init(int req_major, int req_minor, int req_micro)
pygobject_init(-1, -1, -1)

cdef extern from "pygtk/pygtk.h":
    void init_pygtk()
init_pygtk()
# Now all the macros in those header files will work.

cdef extern from "gtk-2.0/gdk/gdktypes.h":
    ctypedef struct cGdkWindow "GdkWindow":
        pass

cdef extern from "gtk-2.0/gdk/gdkevents.h":
    ctypedef enum GdkFilterReturn:
        GDK_FILTER_CONTINUE   # If we ignore the event
        GDK_FILTER_TRANSLATE  # If we converted the event to a GdkEvent
        GDK_FILTER_REMOVE     # If we handled the event and GDK should ignore it

    ctypedef struct GdkXEvent:
        pass
    ctypedef struct GdkEvent:
        pass

    ctypedef GdkFilterReturn (*GdkFilterFunc)(GdkXEvent *, GdkEvent *, void *)
    void gdk_window_add_filter(cGdkWindow * w,
                               GdkFilterFunc filter,
                               void * userdata)

    void gdk_window_remove_filter(cGdkWindow *window,
                               GdkFilterFunc function,
                               void * data)

wheel_event_handler = None
def set_wheel_event_handler(fn):
    global wheel_event_handler
    wheel_event_handler = fn

cdef GdkFilterReturn quartz_event_filter(GdkXEvent * event,
                                    GdkEvent * gdk_event,
                                    void * userdata) with gil:
    cdef NSEvent* nsevent = <NSEvent*> event
    cdef NSEventType event_type = getNSEventType(nsevent)
    cdef void *view
    cdef double deltaX, deltaY
    #log("quartz_event_filter(%#x, %#x, %#x) event type=%i", <uintptr_t> nsevent, <uintptr_t> gdk_event, <uintptr_t> userdata, event_type)
    if event_type==NSScrollWheel:
        try:
            view = getNSEventView(nsevent);
            #log.info(" type=%i, window=%i, deltas=%s", nsevent._type, nsevent._windowNumber, (nsevent.deltaX, nsevent.deltaY, nsevent.deltaZ))
            deltaX = getNSEventScrollingDeltaX(nsevent)
            deltaY = getNSEventScrollingDeltaY(nsevent)
            precise = getPreciseScrollingDeltas(nsevent)
            log("wheel view=%i, deltaX=%f, deltaY=%f, precise=%s, wheel_event_handler=%s", <uintptr_t> view, deltaX, deltaY, precise, wheel_event_handler)
            global wheel_event_handler
            if wheel_event_handler:
                r = wheel_event_handler(<uintptr_t> view, deltaX, deltaY, bool(precise))
                log("%s=%s", wheel_event_handler, r)
                if r:
                    return GDK_FILTER_REMOVE
        except:
            log.warn("Warning: unhandled exception in quartz_event_filter", exc_info=True)
    return GDK_FILTER_CONTINUE


_INIT_QUARTZ_FILTER_DONE = False
def init_quartz_filter():
    """ returns True if we did initialize it, False if it was already initialized """
    global _INIT_QUARTZ_FILTER_DONE
    if _INIT_QUARTZ_FILTER_DONE:
        return False
    gdk_window_add_filter(<cGdkWindow*>0, quartz_event_filter, <void*>0)
    _INIT_QUARTZ_FILTER_DONE = True
    return True

def cleanup_quartz_filter():
    global _INIT_QUARTZ_FILTER_DONE
    if not _INIT_QUARTZ_FILTER_DONE:
        return False
    gdk_window_remove_filter(<cGdkWindow*>0, quartz_event_filter, <void*>0)
    _INIT_QUARTZ_FILTER_DONE = False
    return True
