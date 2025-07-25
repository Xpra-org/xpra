# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.x11.bindings.xlib cimport Display, Window, Atom, Time, Bool, XEvent
from xpra.x11.bindings.display_source cimport get_display
from xpra.x11.bindings.events cimport add_parser, new_x11_event, add_event_type, atom_str

from xpra.log import Logger

log = Logger("x11", "bindings", "fixes")


cdef extern from "X11/extensions/xfixeswire.h":
    unsigned int XFixesCursorNotify
    unsigned long XFixesDisplayCursorNotifyMask
    unsigned int XFixesSelectionNotify


cdef extern from "X11/extensions/Xfixes.h":

    Bool XFixesQueryExtension(Display *, int *event_base, int *error_base)

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


def init_xfixes_events() -> bool:
    cdef Display *display = get_display()
    cdef int event_base = 0
    cdef int error_base = 0
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


cdef object parse_XFSelectionNotify(Display *d, XEvent *e):
    cdef XFixesSelectionNotifyEvent * selectionnotify_e = <XFixesSelectionNotifyEvent*> e
    pyev = new_x11_event(e)
    pyev.window = selectionnotify_e.window
    pyev.subtype = selectionnotify_e.subtype
    pyev.owner = selectionnotify_e.owner
    pyev.selection = atom_str(d, selectionnotify_e.selection)
    pyev.timestamp = int(selectionnotify_e.timestamp)
    pyev.selection_timestamp = int(selectionnotify_e.selection_timestamp)
    return pyev


cdef object parse_CursorNotify(Display *d, XEvent *e):
    cdef object pyev = new_x11_event(e)
    pyev.window = e.xany.window
    cdef XFixesCursorNotifyEvent * cursor_e = <XFixesCursorNotifyEvent*> e
    pyev.cursor_serial = cursor_e.cursor_serial
    pyev.cursor_name = atom_str(d, cursor_e.cursor_name)
    return pyev
