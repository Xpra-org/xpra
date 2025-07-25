# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.x11.bindings.xlib cimport Display, Window, XEvent, Bool
from xpra.x11.bindings.display_source cimport get_display
from xpra.x11.bindings.events cimport add_parser, new_x11_event, add_event_type

from xpra.log import Logger
log = Logger("x11", "bindings", "shape")


cdef extern from "X11/extensions/shape.h":
    Bool XShapeQueryExtension(Display *display, int *event_base, int *error_base)
    ctypedef struct XShapeEvent:
        Window window
        int kind            #ShapeBounding or ShapeClip
        int x, y            #extents of new region
        unsigned width, height
        Bool shaped         #true if the region exists


cdef int ShapeNotify = 0


def init_xshape_events() -> bool:
    cdef Display *display = get_display()
    cdef int event_base = 0, ignored = 0
    if not XShapeQueryExtension(display, &event_base, &ignored):
        log.warn("Warning: XShape extension is not available")
        return False
    global ShapeNotify
    ShapeNotify = event_base
    log("init_xshape_events() ShapeNotify=%d", ShapeNotify)
    add_event_type(ShapeNotify, "ShapeNotify", "x11-shape-event", "")
    add_parser(ShapeNotify, parse_ShapeNotify)
    return True


cdef object parse_ShapeNotify(Display *d, XEvent *e):
    cdef object pyev = new_x11_event(e)
    cdef XShapeEvent *shape_e = <XShapeEvent*> e
    pyev.window = shape_e.window
    pyev.kind = shape_e.kind
    pyev.x = shape_e.x
    pyev.y = shape_e.y
    pyev.width = shape_e.width
    pyev.height = shape_e.height
    pyev.shaped = bool(shape_e.shaped)
    log("parse_ShapeNotify() event=%s", pyev)
    return pyev
