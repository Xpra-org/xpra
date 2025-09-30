# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import List, Dict

from xpra.x11.bindings.xlib cimport (
    Display, Window, XRectangle, Atom, Time, Bool, XEvent, XID,
    XFree, XDefaultRootWindow,
)
from xpra.x11.bindings.display_source cimport get_display
from xpra.x11.bindings.events cimport add_parser, add_event_type, atom_str
from xpra.x11.bindings.core cimport X11CoreBindingsInstance, import_check

from xpra.util.env import envbool
from xpra.log import Logger

import_check("fixes")

log = Logger("x11", "bindings", "fixes")


cdef extern from "X11/extensions/shapeconst.h":
    cdef int ShapeBounding
    cdef int ShapeClip
    cdef int ShapeInput

cdef extern from "X11/extensions/xfixeswire.h":
    unsigned int XFixesCursorNotify
    unsigned long XFixesDisplayCursorNotifyMask
    unsigned int XFixesSelectionNotify

    unsigned int XFixesSetSelectionOwnerNotifyMask
    unsigned int XFixesSelectionWindowDestroyNotifyMask
    unsigned int XFixesSelectionClientCloseNotifyMask

    void XFixesSelectCursorInput(Display *, Window w, long mask)


cdef extern from "X11/extensions/Xfixes.h":

    ctypedef XID XserverRegion

    ctypedef struct XFixesCursorImage:
        short x
        short y
        unsigned short width
        unsigned short height
        unsigned short xhot
        unsigned short yhot
        unsigned long cursor_serial
        unsigned long* pixels
        Atom atom
        char* name

    ctypedef struct XFixesCursorNotifyEvent:
        int type
        unsigned long serial
        Bool send_event
        Display *display
        Window window
        int subtype
        unsigned long cursor_serial
        Time timestamp
        Atom cursor_name

    ctypedef struct XFixesSelectionNotifyEvent:
        int subtype
        Window window
        Window owner
        Atom selection
        Time timestamp
        Time selection_timestamp

    Bool XFixesQueryExtension(Display *, int *event_base, int *error_base)

    XFixesCursorImage* XFixesGetCursorImage(Display *)

    XserverRegion XFixesCreateRegion(Display *, XRectangle *rectangles, int nrectangles)
    void XFixesDestroyRegion(Display *, XserverRegion)

    void XFixesSetWindowShapeRegion(Display *dpy, Window win, int shape_kind, int x_off, int y_off, XserverRegion region)

    void XFixesSelectSelectionInput(Display *dpy, Window win, Atom selection, unsigned long eventMask)


cdef unsigned int init_done = 0
cdef int event_base = 0
cdef int error_base = 0


def init_xfixes_events() -> bool:
    global init_done
    if init_done:
        return event_base > 0
    init_done = 1
    cdef Display *display = get_display()
    if not XFixesQueryExtension(display, &event_base, &error_base):
        log.warn("Warning: XFixes extension is not available")
        return False
    if event_base <= 0:
        log.warn("Warning: XFixes extension returned invalid event base: %d", event_base)
        return False

    cdef int CursorNotify = event_base + XFixesCursorNotify
    add_event_type(CursorNotify, "CursorNotify", "x11-cursor-event", "")
    add_parser(CursorNotify, parse_CursorNotify)
    log("CursorNotify=%d", CursorNotify)

    cdef int XFSelectionNotify = event_base + XFixesSelectionNotify
    add_event_type(XFSelectionNotify, "XFSelectionNotify", "x11-xfixes-selection-notify-event", "")
    add_parser(XFSelectionNotify, parse_XFSelectionNotify)
    log("XFSelectionNotify=%d", XFSelectionNotify)

    return True


cdef dict parse_XFSelectionNotify(Display *d, XEvent *e):
    cdef XFixesSelectionNotifyEvent * selectionnotify_e = <XFixesSelectionNotifyEvent*> e
    return {
        "window": selectionnotify_e.window,
        "subtype": selectionnotify_e.subtype,
        "owner": selectionnotify_e.owner,
        "selection": atom_str(d, selectionnotify_e.selection),
        "timestamp": int(selectionnotify_e.timestamp),
        "selection_timestamp": int(selectionnotify_e.selection_timestamp),
    }


cdef dict parse_CursorNotify(Display *d, XEvent *e):
    cdef XFixesCursorNotifyEvent * cursor_e = <XFixesCursorNotifyEvent*> e
    return {
        "window": cursor_e.window,
        "subtype": cursor_e.subtype,
        "cursor_serial": int(cursor_e.cursor_serial),
        "timestamp": int(cursor_e.timestamp),
        "cursor_name": atom_str(d, cursor_e.cursor_name),
    }


cdef str s(const char *v):
    pytmp = v[:]
    try:
        return pytmp.decode()
    except:
        return str(v[:])


cdef class XFixesBindingsInstance(X11CoreBindingsInstance):

    cdef int checked
    cdef int present

    def hasXFixes(self) -> bool:
        self.context_check("hasXFixes")
        cdef int evbase, errbase
        if not self.checked:
            self.checked = True
            if not envbool("XPRA_X11_XFIXES", True):
                log.warn("XFixes disabled using XPRA_X11_XFIXES")
            else:
                self.present = XFixesQueryExtension(self.display, &evbase, &errbase)
                log("XFixesQueryExtension version present: %s", bool(self.present))
                if self.present:
                    log("XFixesQueryExtension event base=%i, error base=%i", evbase, errbase)
                else:
                    log.warn("Warning: XFixes extension is missing")
        return bool(self.present)

    def get_cursor_image(self) -> List | None:
        self.context_check("get_cursor_image")
        if not self.hasXFixes():
            return None
        cdef XFixesCursorImage* image = NULL
        cdef int n, i = 0
        cdef unsigned char r, g, b, a
        cdef unsigned long argb
        try:
            image = XFixesGetCursorImage(self.display)
            if image==NULL:
                return None
            n = image.width*image.height
            # Warning: we need to iterate over the input one *long* at a time
            # (even though only 4 bytes are set - and longs are 8 bytes on 64-bit..)
            pixels = bytearray(n*4)
            while i<n:
                argb = image.pixels[i] & 0xffffffff
                a = (argb >> 24)   & 0xff
                r = (argb >> 16)   & 0xff
                g = (argb >> 8)    & 0xff
                b = (argb)         & 0xff
                pixels[i*4]     = r
                pixels[i*4+1]   = g
                pixels[i*4+2]   = b
                pixels[i*4+3]   = a
                i += 1
            return [image.x, image.y, image.width, image.height, image.xhot, image.yhot,
                int(image.cursor_serial), bytes(pixels), s(image.name)]
        finally:
            if image!=NULL:
                XFree(image)

    def selectCursorChange(self, on: bool) -> bool:
        self.context_check("selectCursorChange")
        if not self.hasXFixes():
            log.warn("Warning: no cursor change notifications without XFixes support")
            return False
        cdef unsigned int mask = 0
        cdef Window root_window = XDefaultRootWindow(self.display)
        if on:
            mask = XFixesDisplayCursorNotifyMask
        # no return value..
        XFixesSelectCursorInput(self.display, root_window, mask)
        return True

    def selectXFSelectionInput(self, Window window, str selection_str) -> None:
        self.context_check("selectXFSelectionInput")
        cdef unsigned long event_mask = (
            XFixesSetSelectionOwnerNotifyMask |
            XFixesSelectionWindowDestroyNotifyMask |
            XFixesSelectionClientCloseNotifyMask
        )
        cdef Atom selection = self.str_to_atom(selection_str)
        XFixesSelectSelectionInput(self.display, window, selection, event_mask)

    def AllowInputPassthrough(self, Window window) -> None:
        self.context_check("AllowInputPassthrough")
        cdef XserverRegion region = XFixesCreateRegion(self.display, NULL, 0)
        XFixesSetWindowShapeRegion(self.display, window, ShapeBounding, 0, 0, 0)
        XFixesSetWindowShapeRegion(self.display, window, ShapeInput, 0, 0, region)
        XFixesDestroyRegion(self.display, region)


cdef XFixesBindingsInstance singleton = None


def XFixesBindings() -> XFixesBindingsInstance:
    global singleton
    if singleton is None:
        singleton = XFixesBindingsInstance()
    return singleton
