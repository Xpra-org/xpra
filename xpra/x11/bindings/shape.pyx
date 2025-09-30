# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Dict, Tuple

from xpra.x11.bindings.xlib cimport Display, Window, XRectangle, XEvent, Bool, Status
from xpra.x11.bindings.display_source cimport get_display
from xpra.x11.bindings.events cimport add_parser, add_event_type
from xpra.x11.bindings.core cimport X11CoreBindingsInstance, import_check
from libc.stdlib cimport free, malloc        # pylint: disable=syntax-error

from xpra.log import Logger

import_check("shape")

log = Logger("x11", "bindings", "shape")


cdef extern from "X11/extensions/shape.h":
    Bool XShapeQueryExtension(Display *display, int *event_base, int *error_base)
    ctypedef struct XShapeEvent:
        Window window
        int kind            #ShapeBounding or ShapeClip
        int x, y            #extents of new region
        unsigned width, height
        Bool shaped         #true if the region exists

    Status XShapeQueryVersion(Display *display, int *major_version, int *minor_version)
    Status XShapeQueryExtents(Display *display, Window window, Bool *bounding_shaped, int *x_bounding, int *y_bounding, unsigned int *w_bounding, unsigned int *h_bounding, Bool *clip_shaped, int *x_clip, int *y_clip, unsigned int *w_clip, unsigned int *h_clip)
    void XShapeSelectInput(Display *display, Window window, unsigned long mask)
    unsigned long XShapeInputSelected(Display *display, Window window)
    XRectangle *XShapeGetRectangles(Display *display, Window window, int kind, int *count, int *ordering)

    void XShapeCombineRectangles(Display *display, Window dest, int dest_kind, int x_off, int y_off, XRectangle *rectangles, int n_rects, int op, int ordering)

    cdef int ShapeBounding
    cdef int ShapeClip
    cdef int ShapeInput


SHAPE_KIND: Dict[int, str] = {
    ShapeBounding   : "Bounding",
    ShapeClip       : "Clip",
    ShapeInput      : "ShapeInput",
}


def init_xshape_events() -> bool:
    cdef Display *display = get_display()
    cdef int event_base = 0, ignored = 0
    if not XShapeQueryExtension(display, &event_base, &ignored):
        log.warn("Warning: XShape extension is not available")
        return False
    cdef int ShapeNotify = event_base
    log("init_xshape_events() ShapeNotify=%d", ShapeNotify)
    add_event_type(ShapeNotify, "ShapeNotify", "x11-shape-event", "")
    add_parser(ShapeNotify, parse_ShapeNotify)
    return True


cdef dict parse_ShapeNotify(Display *d, XEvent *e):
    cdef XShapeEvent *shape_e = <XShapeEvent*> e
    return {
        "window": shape_e.window,
        "kind": shape_e.kind,
        "x": shape_e.x,
        "y": shape_e.y,
        "width": shape_e.width,
        "height": shape_e.height,
        "shaped": bool(shape_e.shaped),
    }


cdef class XShapeBindingsInstance(X11CoreBindingsInstance):
    cdef int checked
    cdef int present

    def hasXShape(self) -> bool:
        cdef int event_base = 0, ignored = 0
        cdef int cmajor, cminor
        if not self.checked:
            self.checked = 1
            if not XShapeQueryExtension(self.display, &event_base, &ignored):
                log.warn("X11 extension XShape not available")
                self.present = False
            else:
                log("XShape extension event_base=%i", event_base)
                if not XShapeQueryVersion(self.display, &cmajor, &cminor):
                    log.warn("XShape version query failed")
                    self.present = False
                else:
                    log("found XShape extension version %i.%i", cmajor, cminor)
                    self.present = True
        log("hasXShape()=%s", self.present)
        return self.present

    def XShapeSelectInput(self, Window window) -> None:
        self.context_check("XShapeSelectInput")
        cdef int ShapeNotifyMask = 1
        XShapeSelectInput(self.display, window, ShapeNotifyMask)

    def XShapeQueryExtents(self, Window window) -> Tuple[Tuple, Tuple]:
        self.context_check("XShapeQueryExtents")
        cdef Bool bounding_shaped, clip_shaped
        cdef int x_bounding, y_bounding, x_clip, y_clip
        cdef unsigned int w_bounding, h_bounding, w_clip, h_clip
        if not XShapeQueryExtents(self.display, window,
                                  &bounding_shaped, &x_bounding, &y_bounding, &w_bounding, &h_bounding,
                                  &clip_shaped, &x_clip, &y_clip, &w_clip, &h_clip):
            return None
        return (
            (bounding_shaped, x_bounding, y_bounding, w_bounding, h_bounding),
            (clip_shaped, x_clip, y_clip, w_clip, h_clip)
        )

    def XShapeGetRectangles(self, Window window, int kind) -> List[Tuple[int, int, int, int]]:
        self.context_check("XShapeGetRectangles")
        cdef int count, ordering
        cdef XRectangle* rect = XShapeGetRectangles(self.display, window, kind, &count, &ordering)
        if rect==NULL or count<=0:
            return []
        rectangles = []
        cdef int i
        for i in range(count):
            rectangles.append((rect[i].x, rect[i].y, rect[i].width, rect[i].height))
        return rectangles

    def XShapeCombineRectangles(self, Window window, int kind, int x_off, int y_off, rectangles) -> None:
        self.context_check("XShapeCombineRectangles")
        cdef int n_rects = len(rectangles)
        cdef int op = 0     #SET
        cdef int ordering = 0   #Unsorted
        cdef size_t l = sizeof(XRectangle) * n_rects
        cdef XRectangle *rects = <XRectangle*> malloc(l)
        if rects==NULL:
            raise RuntimeError("failed to allocate %i bytes of memory for xshape rectangles" % l)
        cdef int i = 0
        for r in rectangles:
            rects[i].x = r[0]
            rects[i].y = r[1]
            rects[i].width = r[2]
            rects[i].height = r[3]
            i += 1
        XShapeCombineRectangles(self.display, window, kind, x_off, y_off,
                                rects, n_rects, op, ordering)
        free(rects)


cdef XShapeBindingsInstance singleton = None


def XShapeBindings() -> XShapeBindingsInstance:
    global singleton
    if singleton is None:
        singleton = XShapeBindingsInstance()
    return singleton
