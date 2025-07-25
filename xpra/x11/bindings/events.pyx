# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from time import monotonic
from typing import Dict, Tuple
from collections.abc import Callable

from xpra.util.str_fn import strtobytes
from xpra.gtk.error import XError, xsync
from xpra.x11.common import X11Event
from xpra.util.str_fn import csv

from xpra.log import Logger
log = Logger("x11", "bindings")
verbose = Logger("x11", "bindings", "verbose")


from xpra.x11.bindings.xlib cimport (
    Display, Window, Visual, XID, XRectangle, Atom, Time, CARD32, Bool,
    XEvent, XSelectionRequestEvent, XSelectionClearEvent, XCrossingEvent,
    XSelectionEvent, XCreateWindowEvent, XCreateWindowEvent,
    XFree, XGetErrorText,
    XDefaultRootWindow,
    XGetAtomName,
)
from libc.stdint cimport uintptr_t


DEF XNone = 0

cdef extern from "X11/Xlib.h":
    int NotifyNormal

    int BadWindow
    int MapRequest
    int ConfigureRequest
    int SelectionRequest
    int SelectionClear
    int FocusIn
    int FocusOut
    int KeymapNotify
    int Expose
    int GraphicsExpose
    int NoExpose
    int VisibilityNotify
    int ClientMessage
    int CreateNotify
    int MapNotify
    int UnmapNotify
    int DestroyNotify
    int ConfigureNotify
    int ReparentNotify
    int GravityNotify
    int ResizeRequest
    int CirculateNotify
    int CirculateRequest
    int SelectionNotify
    int ColormapNotify
    int MappingNotify
    int PropertyNotify
    int KeyPress
    int KeyRelease
    int ButtonPress
    int ButtonRelease
    int EnterNotify
    int LeaveNotify
    int MotionNotify
    int GenericEvent


cdef extern from "X11/extensions/xfixeswire.h":
    unsigned int XFixesCursorNotify
    unsigned long XFixesDisplayCursorNotifyMask
    unsigned int XFixesSelectionNotify


cdef extern from "X11/extensions/shape.h":
    Bool XShapeQueryExtension(Display *display, int *event_base, int *error_base)
    ctypedef struct XShapeEvent:
        Window window
        int kind            #ShapeBounding or ShapeClip
        int x, y            #extents of new region
        unsigned width, height
        Bool shaped         #true if the region exists


cdef extern from "X11/extensions/Xdamage.h":
    ctypedef XID Damage
    unsigned int XDamageNotify
    ctypedef struct XDamageNotifyEvent:
        Damage damage
        int level
        Bool more
        XRectangle area
    Bool XDamageQueryExtension(Display *, int * event_base, int * error_base)


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
    Bool XkbQueryExtension(Display *, int *opcodeReturn, int *eventBaseReturn, int *errorBaseReturn, int *majorRtrn, int *minorRtrn)


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


cdef int CursorNotify = -1
cdef int XKBNotify = -1
cdef int ShapeNotify = -1
cdef int XFSelectionNotify = -1


cdef int get_XKB_event_base(Display *xdisplay) noexcept:
    cdef int opcode = 0
    cdef int event_base = 0
    cdef int error_base = 0
    cdef int major = 0
    cdef int minor = 0
    if not XkbQueryExtension(xdisplay, &opcode, &event_base, &error_base, &major, &minor):
        log.warn("Warning: Xkb extension is not available")
        return -1
    verbose(f"get_XKB_event_base(%#x)=%i", <uintptr_t> xdisplay, event_base)
    return event_base


cdef int get_XFixes_event_base(Display *xdisplay) noexcept:
    cdef int event_base = 0
    cdef int error_base = 0
    if not XFixesQueryExtension(xdisplay, &event_base, &error_base):
        log.warn("Warning: XFixes extension is not available")
        return -1
    verbose("get_XFixes_event_base(%#x)=%i", <uintptr_t> xdisplay, event_base)
    assert event_base>0, "invalid event base for XFixes"
    return event_base


cdef int get_XDamage_event_base(Display *xdisplay) noexcept:
    cdef int event_base = 0
    cdef int error_base = 0
    if not XDamageQueryExtension(xdisplay, &event_base, &error_base):
        log.warn("Warning: XDamage extension is not available")
        return -1
    verbose("get_XDamage_event_base(%#x)=%i", <uintptr_t> xdisplay, event_base)
    assert event_base>0, "invalid event base for XDamage"
    return event_base


cdef int get_XShape_event_base(Display *xdisplay) noexcept:
    cdef int event_base = 0, ignored = 0
    if not XShapeQueryExtension(xdisplay, &event_base, &ignored):
        log.warn("Warning: XShape extension is not available")
        return -1
    return event_base


cdef void init_x11_events(Display *display):
    add_x_event_signals({
        MapRequest          : ("", "x11-child-map-request-event"),
        ConfigureRequest    : ("", "x11-child-configure-request-event"),
        SelectionRequest    : ("x11-selection-request", ""),
        SelectionClear      : ("x11-selection-clear", ""),
        FocusIn             : ("x11-focus-in-event", ""),
        FocusOut            : ("x11-focus-out-event", ""),
        ClientMessage       : ("x11-client-message-event", ""),
        CreateNotify        : ("x11-create-event", ""),
        MapNotify           : ("x11-map-event", "x11-child-map-event"),
        UnmapNotify         : ("x11-unmap-event", "x11-child-unmap-event"),
        DestroyNotify       : ("x11-destroy-event", ""),
        ConfigureNotify     : ("x11-configure-event", ""),
        ReparentNotify      : ("x11-reparent-event", ""),
        PropertyNotify      : ("x11-property-notify-event", ""),
        KeyPress            : ("x11-key-press-event", ""),
        EnterNotify         : ("x11-enter-event", ""),
        LeaveNotify         : ("x11-leave-event", ""),
        MotionNotify        : ("x11-motion-event", "")       #currently unused, just defined for debugging purposes
    })
    add_x_event_type_names({
        KeyPress            : "KeyPress",
        KeyRelease          : "KeyRelease",
        ButtonPress         : "ButtonPress",
        ButtonRelease       : "ButtonRelease",
        MotionNotify        : "MotionNotify",
        EnterNotify         : "EnterNotify",
        LeaveNotify         : "LeaveNotify",
        FocusIn             : "FocusIn",
        FocusOut            : "FocusOut",
        KeymapNotify        : "KeymapNotify",
        Expose              : "Expose",
        GraphicsExpose      : "GraphicsExpose",
        NoExpose            : "NoExpose",
        VisibilityNotify    : "VisibilityNotify",
        CreateNotify        : "CreateNotify",
        DestroyNotify       : "DestroyNotify",
        UnmapNotify         : "UnmapNotify",
        MapNotify           : "MapNotify",
        MapRequest          : "MapRequest",
        ReparentNotify      : "ReparentNotify",
        ConfigureNotify     : "ConfigureNotify",
        ConfigureRequest    : "ConfigureRequest",
        GravityNotify       : "GravityNotify",
        ResizeRequest       : "ResizeRequest",
        CirculateNotify     : "CirculateNotify",
        CirculateRequest    : "CirculateRequest",
        PropertyNotify      : "PropertyNotify",
        SelectionClear      : "SelectionClear",
        SelectionRequest    : "SelectionRequest",
        SelectionNotify     : "SelectionNotify",
        ColormapNotify      : "ColormapNotify",
        ClientMessage       : "ClientMessage",
        MappingNotify       : "MappingNotify",
        GenericEvent        : "GenericEvent",
    })
    cdef int event_base = get_XShape_event_base(display)
    if event_base>=0:
        global ShapeNotify
        ShapeNotify = event_base
        add_event_type(ShapeNotify, "ShapeNotify", "x11-shape-event")
    event_base = get_XKB_event_base(display)
    if event_base>=0:
        global XKBNotify
        XKBNotify = event_base
        add_event_type(XKBNotify, "XKBNotify", "x11-xkb-event")
    event_base = get_XFixes_event_base(display)
    if event_base>=0:
        global CursorNotify
        CursorNotify = XFixesCursorNotify+event_base
        add_event_type(CursorNotify, "CursorNotify", "x11-cursor-event")

        global XFSelectionNotify
        XFSelectionNotify = XFixesSelectionNotify+event_base
        add_event_type(XFSelectionNotify, "XFSelectionNotify", "x11-xfixes-selection-notify-event")
    event_base = get_XDamage_event_base(display)
    if event_base>0:
        global DamageNotify
        DamageNotify = XDamageNotify+event_base
        add_event_type(DamageNotify, "DamageNotify", "x11-damage-event")
    set_debug_events()


cdef void add_event_type(event: int, name: str, event_name: str, child_event_name: str = ""):
    add_x_event_type_name(event, name)
    add_x_event_signal(event, (event_name, child_event_name))


x_event_signals : Dict[int, Tuple[str, str]] = {}


def add_x_event_signal(event: int, mapping: Tuple[str, str]) -> None:
    x_event_signals[event] = mapping


def add_x_event_signals(event_signals: Dict[int, Tuple[str, str]]) -> None:
    x_event_signals.update(event_signals)


def get_x_event_signals(event: int) -> Tuple[str, str]:
    return x_event_signals.get(event)


x_event_type_names : Dict[int, str] = {}
names_to_event_type : Dict[str, int] = {}


def add_x_event_type_name(event: int, name: str) -> None:
    x_event_type_names[event] = name
    names_to_event_type[name] = event


def add_x_event_type_names(event_type_names: Dict[int, str]) -> None:
    x_event_type_names.update(event_type_names)
    for k,v in event_type_names.items():
        names_to_event_type[v] = k
    verbose("x_event_signals=%s", x_event_signals)
    verbose("event_type_names=%s", x_event_type_names)
    verbose("names_to_event_type=%s", names_to_event_type)


def get_x_event_type_name(event: int) -> str:
    return x_event_type_names.get(event, "")


def set_debug_events() -> None:
    global debug_route_events
    XPRA_X11_DEBUG_EVENTS = os.environ.get("XPRA_X11_DEBUG_EVENTS", "")
    debug_set = set()
    ignore_set = set()
    for n in XPRA_X11_DEBUG_EVENTS.split(","):
        name = n.strip()
        if len(name)==0:
            continue
        if name[0]=="-":
            event_set = ignore_set
            name = name[1:]
        else:
            event_set = debug_set
        if name in ("*", "all"):
            events = names_to_event_type.keys()
        elif name in names_to_event_type:
            events = [name]
        else:
            log("unknown X11 debug event type: %s", name)
            continue
        #add to correct set:
        for e in events:
            event_set.add(e)
    events = debug_set.difference(ignore_set)
    debug_route_events = [names_to_event_type.get(x) for x in events]
    if len(events)>0:
        log.warn("debugging of X11 events enabled for:")
        log.warn(" %s", csv(events))
        log.warn(" event codes: %s", csv(debug_route_events))


x_event_parsers : Dict[int, Callable] = {}


def add_x_event_parser(extension_opcode: int, parser : Callable) -> None:
    x_event_parsers[extension_opcode] = parser


cdef str atom_str(Display *display, Atom atom):
    if not atom:
        return ""
    cdef char* atom_name = NULL
    try:
        with xsync:
            atom_name = XGetAtomName(display, atom)
    except XError:
        log.error(f"Error: invalid atom {atom:x}")
        return ""
    r = ""
    if atom_name!=NULL:
        r = atom_name.decode("latin1")
        XFree(atom_name)
    return r



cdef object new_x11_event(XEvent *e):
    cdef int etype = e.type
    cdef str event_type = x_event_type_names.get(etype) or str(etype)
    cdef object pyev = X11Event(event_type)
    pyev.type = etype
    pyev.send_event = bool(e.xany.send_event)
    pyev.serial = e.xany.serial
    if etype != XKBNotify:
        pyev.delivered_to = e.xany.window
    return pyev


cdef object parse_DamageNotify(Display *d, XEvent *e):
    cdef XDamageNotifyEvent * damage_e = <XDamageNotifyEvent*>e
    pyev = new_x11_event(e)
    pyev.window = e.xany.window
    pyev.damage = damage_e.damage
    pyev.x = damage_e.area.x
    pyev.y = damage_e.area.y
    pyev.width = damage_e.area.width
    pyev.height = damage_e.area.height
    return pyev


cdef object parse_MapRequest(Display *d, XEvent *e):
    pyev = new_x11_event(e)
    pyev.window = e.xmaprequest.window
    return pyev


cdef object parse_ConfigureRequest(Display *d, XEvent *e):
    pyev = new_x11_event(e)
    pyev.window = e.xconfigurerequest.window
    pyev.x = e.xconfigurerequest.x
    pyev.y = e.xconfigurerequest.y
    pyev.width = e.xconfigurerequest.width
    pyev.height = e.xconfigurerequest.height
    pyev.border_width = e.xconfigurerequest.border_width
    # In principle there are two cases here: .above is
    # XNone (i.e. not specified in the original request),
    # or .above is an invalid window (i.e. it was
    # specified by the client, but it specified something
    # weird).  I don't see any reason to handle these
    # differently, though.
    pyev.above = e.xconfigurerequest.above
    pyev.detail = e.xconfigurerequest.detail
    pyev.value_mask = e.xconfigurerequest.value_mask
    return pyev


cdef object parse_SelectionRequest(Display *d, XEvent *e):
    cdef XSelectionRequestEvent * selectionrequest_e = <XSelectionRequestEvent*> e
    pyev = new_x11_event(e)
    pyev.window = selectionrequest_e.owner
    pyev.requestor = selectionrequest_e.requestor
    pyev.selection = atom_str(d, selectionrequest_e.selection)
    pyev.target = atom_str(d, selectionrequest_e.target)
    pyev.property = atom_str(d, selectionrequest_e.property)
    pyev.time = int(selectionrequest_e.time)
    return pyev


cdef object parse_SelectionClear(Display *d, XEvent *e):
    cdef XSelectionClearEvent * selectionclear_e = <XSelectionClearEvent*> e
    pyev = new_x11_event(e)
    pyev.window = selectionclear_e.window
    pyev.selection = atom_str(d, selectionclear_e.selection)
    pyev.time = int(selectionclear_e.time)
    return pyev

cdef object parse_SelectionNotify(Display *d, XEvent *e):
    cdef XSelectionEvent * selection_e = <XSelectionEvent*> e
    pyev = new_x11_event(e)
    pyev.window = selection_e.requestor
    pyev.selection = atom_str(d, selection_e.selection)
    pyev.target = atom_str(d, selection_e.target)
    pyev.property = atom_str(d, selection_e.property)
    pyev.time = int(selection_e.time)
    return pyev


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


cdef object parse_ResizeRequest(Display *d, XEvent *e):
    pyev = new_x11_event(e)
    pyev.window = e.xresizerequest.window
    pyev.width = e.xresizerequest.width
    pyev.height = e.xresizerequest.height
    return pyev


cdef object _parse_Focus(Display *d, XEvent *e):
    pyev = new_x11_event(e)
    pyev.window = e.xfocus.window
    pyev.mode = e.xfocus.mode
    pyev.detail = e.xfocus.detail
    return pyev


cdef object parse_FocusIn(Display *d, XEvent *e):
    return _parse_Focus(d, e)


cdef object parse_FocusOut(Display *d, XEvent *e):
    return _parse_Focus(d, e)


cdef object _parse_EnterLeave(Display *d, XEvent *e):
    cdef XCrossingEvent * crossing_e = <XCrossingEvent*> e
    pyev = new_x11_event(e)
    pyev.window = crossing_e.window
    pyev.mode = crossing_e.mode
    pyev.detail = crossing_e.detail
    pyev.subwindow = crossing_e.subwindow
    pyev.focus = bool(crossing_e.focus)
    return pyev


cdef object parse_EnterNotify(Display *d, XEvent *e):
    return _parse_EnterLeave(d, e)


cdef object parse_LeaveNotify(Display *d, XEvent *e):
    return _parse_EnterLeave(d, e)


cdef object parse_CreateNotify(Display *d, XEvent *e):
    cdef object pyev = new_x11_event(e)
    pyev.window = e.xcreatewindow.window
    pyev.width = e.xcreatewindow.width
    pyev.height = e.xcreatewindow.height
    return pyev


cdef object parse_MapNotify(Display *d, XEvent *e):
    cdef object pyev = new_x11_event(e)
    pyev.window = e.xmap.window
    pyev.override_redirect = bool(e.xmap.override_redirect)
    return pyev


cdef object parse_UnmapNotify(Display *d, XEvent *e):
    cdef object pyev = new_x11_event(e)
    pyev.window = e.xunmap.window
    pyev.from_configure = bool(e.xunmap.from_configure)
    return pyev


cdef object parse_DestroyNotify(Display *d, XEvent *e):
    cdef object pyev = new_x11_event(e)
    pyev.window = e.xdestroywindow.window
    return pyev


cdef object parse_PropertyNotify(Display *d, XEvent *e):
    cdef object pyev = new_x11_event(e)
    pyev.window = e.xany.window
    pyev.atom = atom_str(d, e.xproperty.atom)
    pyev.time = e.xproperty.time
    return pyev


cdef object parse_ConfigureNotify(Display *d, XEvent *e):
    cdef object pyev = new_x11_event(e)
    pyev.window = e.xconfigure.window
    pyev.x = e.xconfigure.x
    pyev.y = e.xconfigure.y
    pyev.width = e.xconfigure.width
    pyev.height = e.xconfigure.height
    pyev.border_width = e.xconfigure.border_width
    pyev.above = e.xconfigure.above
    pyev.override_redirect = bool(e.xconfigure.override_redirect)
    return pyev


cdef object parse_CirculateNotify(Display *d, XEvent *e):
    cdef object pyev = new_x11_event(e)
    pyev.window = e.xcirculaterequest.window
    pyev.place = e.xcirculaterequest.place
    return pyev


cdef object parse_ReparentNotify(Display *d, XEvent *e):
    cdef object pyev = new_x11_event(e)
    pyev.window = e.xreparent.window
    return pyev


cdef object parse_KeyPress(Display *d, XEvent *e):
    cdef object pyev = new_x11_event(e)
    pyev.window = e.xany.window
    pyev.hardware_keycode = e.xkey.keycode
    pyev.state = e.xkey.state
    return pyev


cdef object parse_CursorNotify(Display *d, XEvent *e):
    cdef object pyev = new_x11_event(e)
    pyev.window = e.xany.window
    cdef XFixesCursorNotifyEvent * cursor_e = <XFixesCursorNotifyEvent*> e
    pyev.cursor_serial = cursor_e.cursor_serial
    pyev.cursor_name = atom_str(d, cursor_e.cursor_name)
    return pyev


cdef object parse_MotionNotify(Display *d, XEvent *e):
    cdef object pyev = new_x11_event(e)
    pyev.window = e.xmotion.window
    pyev.root = e.xmotion.root
    pyev.subwindow = e.xmotion.subwindow
    pyev.time = e.xmotion.time
    pyev.x = e.xmotion.x
    pyev.y = e.xmotion.y
    pyev.x_root = e.xmotion.x_root
    pyev.y_root = e.xmotion.y_root
    pyev.state = e.xmotion.state
    pyev.is_hint = e.xmotion.is_hint != NotifyNormal
    #pyev.same_screen = bool(e.xmotion.same_screen)
    return pyev


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
    return pyev


cdef object parse_ClientMessage(Display *d, XEvent *e):
    cdef object pyev = new_x11_event(e)
    pyev.window = e.xany.window
    if int(e.xclient.message_type) > 2**32:
        log.warn("Warning: Xlib claims that this ClientEvent's 32-bit")
        log.warn(f" message_type is {e.xclient.message_type}.")
        log.warn(" note that this is >2^32.")
        log.warn(" this makes no sense, so I'm ignoring it")
        return None
    pyev.message_type = atom_str(d, e.xclient.message_type)
    pyev.format = e.xclient.format
    pieces = []
    if pyev.format == 32:
        for i in range(5):
            # Mask with 0xffffffff to prevent sign-extension on
            # architectures where Python's int is 64-bits.
            pieces.append(int(e.xclient.data.l[i]) & 0xffffffff)
    elif pyev.format == 16:
        for i in range(10):
            pieces.append(int(e.xclient.data.s[i]))
    elif pyev.format == 8:
        for i in range(20):
            pieces.append(int(e.xclient.data.b[i]))
    else:
        log.warn(f"Warning: ignoring ClientMessage {pyev.message_type!r} with format={pyev.format}")
        return None
    pyev.data = tuple(pieces)
    return pyev


cdef object parse_XKBNotify(Display *d, XEvent *e):
    cdef XkbAnyEvent * xkb_e = <XkbAnyEvent*> e
    # note we could just cast directly to XkbBellNotifyEvent
    # but this would be dirty, and we may want to catch
    # other types of XKB events in the future
    verbose("XKBNotify event received xkb_type=%s", xkb_e.xkb_type)
    if xkb_e.xkb_type != XkbBellNotify:
        return None
    bell_e = <XkbBellNotifyEvent*>e
    cdef object pyev = new_x11_event(e)
    pyev.subtype = "bell"
    pyev.device = int(bell_e.device)
    pyev.percent = int(bell_e.percent)
    pyev.pitch = int(bell_e.pitch)
    pyev.duration = int(bell_e.duration)
    pyev.bell_class = int(bell_e.bell_class)
    pyev.bell_id = int(bell_e.bell_id)
    # no idea why window is not set in XkbBellNotifyEvent
    # since we can fire it from a specific window
    # but we need one for the dispatch logic, so use root if unset
    if bell_e.window != 0:
        verbose("using bell_e.window=%#x", bell_e.window)
        pyev.window = bell_e.window
    else:
        pyev.window = XDefaultRootWindow(d)
        verbose("bell using root window=%#x", pyev.window)
    pyev.event_only = bool(bell_e.event_only)
    pyev.delivered_to = pyev.window
    pyev.window_model = None
    pyev.bell_name = atom_str(d, bell_e.name)
    return pyev



cdef object parse_xevent(Display *d, XEvent *e):
    cdef int etype = e.type
    global x_event_type_names, x_event_signals
    event_type = x_event_type_names.get(etype, etype)
    if e.xany.send_event and etype not in (ClientMessage, UnmapNotify):
        log("parse_xevent ignoring %s send_event", event_type)
        return None

    if etype == GenericEvent:
        global x_event_parsers
        parser = x_event_parsers.get(e.xcookie.extension)
        if parser:
            log("calling GenericEvent parser %s(%s)", parser, <uintptr_t> &e.xcookie)
            return parser(<uintptr_t> &e.xcookie)
        log("no GenericEvent parser for extension %s", e.xcookie.extension)
        return None

    cdef object event_args = x_event_signals.get(etype)
    if event_args is None:
        log("no signal handler for %s", event_type)
        return None
    log("parse_xevent event=%s/%s window=%#x", event_args, event_type, e.xany.window)

    if etype == DamageNotify:
        return parse_DamageNotify(d, e)
    if etype == MapRequest:
        return parse_MapRequest(d, e)
    if etype == ConfigureRequest:
        return parse_ConfigureRequest(d, e)
    if etype == SelectionRequest:
        return parse_SelectionRequest(d, e)
    if etype == SelectionClear:
        return parse_SelectionClear(d, e)
    if etype == SelectionNotify:
        return parse_SelectionNotify(d, e)
    if etype == XFSelectionNotify:
        return parse_XFSelectionNotify(d, e)
    if etype == ResizeRequest:
        return parse_ResizeRequest(d, e)
    if etype == FocusIn:
        return parse_FocusIn(d, e)
    if etype == FocusOut:
        return parse_FocusOut(d, e)
    if etype == EnterNotify:
        return parse_EnterNotify(d, e)
    if etype == LeaveNotify:
        return parse_LeaveNotify(d, e)
    if etype == CreateNotify:
        return parse_CreateNotify(d, e)
    if etype == MapNotify:
        return parse_MapNotify(d, e)
    if etype == UnmapNotify:
        return parse_UnmapNotify(d, e)
    if etype == DestroyNotify:
        return parse_DestroyNotify(d, e)
    if etype == PropertyNotify:
        return parse_PropertyNotify(d, e)
    if etype == ConfigureNotify:
        return parse_ConfigureNotify(d, e)
    if etype == CirculateNotify:
        return parse_CirculateNotify(d, e)
    if etype == ReparentNotify:
        return parse_ReparentNotify(d, e)
    if etype == KeyPress:
        return parse_KeyPress(d, e)
    if etype == CursorNotify:
        return parse_CursorNotify(d, e)
    if etype == MotionNotify:
        return parse_MotionNotify(d, e)
    if etype == ShapeNotify:
        return parse_ShapeNotify(d, e)
    if etype == ClientMessage:
        return parse_ClientMessage(d, e)
    if etype == XKBNotify:
        return parse_XKBNotify(d, e)
    log.info("not handled: %s", x_event_type_names.get(etype, etype))
    return None
