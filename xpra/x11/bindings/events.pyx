# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Dict, Tuple
from collections.abc import Callable

from xpra.gtk.error import XError, xsync
from xpra.x11.common import X11Event
from xpra.util.str_fn import csv

from xpra.log import Logger

log = Logger("x11", "bindings", "events")


from xpra.x11.bindings.xlib cimport (
    Display, Window, Visual, XID, XRectangle, Atom, Time, CARD32, Bool,
    XEvent, XSelectionRequestEvent, XSelectionClearEvent, XCrossingEvent,
    XSelectionEvent, XCreateWindowEvent, XCreateWindowEvent,
    XFree,
    XDefaultRootWindow,
    XGetAtomName,
)
from libc.stdint cimport uintptr_t


cdef extern from "X11/Xlib.h":
    int NotifyNormal

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
        MotionNotify        : ("x11-motion-event", "")
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
    set_debug_events()


cdef PARSE_XEVENT[256] parsers
for i in range(256):
    parsers[i] = NULL


cdef void add_parser(unsigned int event, PARSE_XEVENT parser):
    """
    Add a parser for the given event type.
    """
    if event < 0 or event >= 256:
        raise ValueError(f"Invalid event type: {event}")
    parsers[event] = parser


cdef void add_event_type(int event, str name, str event_name, str child_event_name):
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


add_parser(GenericEvent, parse_GenericEvent)
add_parser(MapRequest, parse_MapRequest)
add_parser(ConfigureRequest, parse_ConfigureRequest)
add_parser(SelectionRequest, parse_SelectionRequest)
add_parser(SelectionClear, parse_SelectionClear)
add_parser(SelectionNotify, parse_SelectionNotify)
add_parser(ResizeRequest, parse_ResizeRequest)
add_parser(FocusIn, parse_FocusIn)
add_parser(FocusOut, parse_FocusOut)
add_parser(EnterNotify, parse_EnterNotify)
add_parser(LeaveNotify, parse_LeaveNotify)
add_parser(CreateNotify, parse_CreateNotify)
add_parser(MapNotify, parse_MapNotify)
add_parser(UnmapNotify, parse_UnmapNotify)
add_parser(DestroyNotify, parse_DestroyNotify)
add_parser(PropertyNotify, parse_PropertyNotify)
add_parser(ConfigureNotify, parse_ConfigureNotify)
add_parser(CirculateNotify, parse_CirculateNotify)
add_parser(ReparentNotify, parse_ReparentNotify)
add_parser(KeyPress, parse_KeyPress)
add_parser(MotionNotify, parse_MotionNotify)
add_parser(ClientMessage, parse_ClientMessage)


def add_x_event_type_name(event: int, name: str) -> None:
    x_event_type_names[event] = name
    names_to_event_type[name] = event


def add_x_event_type_names(event_type_names: Dict[int, str]) -> None:
    x_event_type_names.update(event_type_names)
    for k,v in event_type_names.items():
        names_to_event_type[v] = k
    log("x_event_signals=%s", x_event_signals)
    log("event_type_names=%s", x_event_type_names)
    log("names_to_event_type=%s", names_to_event_type)


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
    pyev.delivered_to = e.xany.window
    return pyev


cdef object parse_GenericEvent(Display *d, XEvent *e):
    global x_event_parsers
    pyparser = x_event_parsers.get(e.xcookie.extension)
    if pyparser:
        log("calling GenericEvent parser %s(%s)", pyparser, <uintptr_t> &e.xcookie)
        return pyparser(<uintptr_t> &e.xcookie)
    log("no GenericEvent parser for extension %s", e.xcookie.extension)
    return None


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


cdef object parse_xevent(Display *d, XEvent *e):
    cdef int etype = e.type
    global x_event_type_names, x_event_signals
    event_type = x_event_type_names.get(etype, etype)
    if e.xany.send_event and etype not in (ClientMessage, UnmapNotify):
        log("parse_xevent ignoring %s send_event", event_type)
        return None

    cdef object event_args = x_event_signals.get(etype)
    if etype != GenericEvent and event_args is None:
        log("no signal handler for %s", event_type)
        return None

    log("parse_xevent event=%s/%s window=%#x", event_args, event_type, e.xany.window)
    cdef PARSE_XEVENT parser = parsers[etype]
    if parser is NULL:
        log.warn("no parser for %s/%s", event_type, etype)
        return None
    return parser(d, e)
