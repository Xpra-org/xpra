# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from time import monotonic
from typing import Dict, Tuple
from collections.abc import Callable

from xpra.x11.error import XError, xsync
from xpra.x11.common import X11Event
from xpra.util.str_fn import csv

from xpra.log import Logger

log = Logger("x11", "bindings", "events")


from xpra.x11.bindings.display_source cimport get_display
from xpra.x11.bindings.xlib cimport (
    Display, Atom, Bool, Status,
    XEvent, XSelectionRequestEvent, XSelectionClearEvent, XCrossingEvent,
    XSelectionEvent, XConfigureRequestEvent,
    XFree,
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


cdef void init_x11_events():
    x_event_signals.update({
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
        MotionNotify        : ("x11-motion-event", ""),
        GenericEvent        : ("x11-generic-event", ""),
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
    from xpra.x11.dispatch import set_debug_events
    set_debug_events()


DEF MAX_XEVENTS = 256
cdef PARSE_XEVENT[MAX_XEVENTS] parsers
for i in range(MAX_XEVENTS):
    parsers[i] = NULL


cdef void add_parser(unsigned int event, PARSE_XEVENT parser) noexcept:
    """
    Add a parser for the given event type.
    """
    if event < 0 or event >= MAX_XEVENTS:
        raise ValueError(f"Invalid event type: {event}")
    parsers[event] = parser


cdef void add_event_type(int event, str name, str event_name, str child_event_name) noexcept:
    add_x_event_type_name(event, name)
    add_x_event_signal(event, (event_name, child_event_name))


x_event_signals : Dict[int, Tuple[str, str]] = {}


def add_x_event_signal(event: int, mapping: Tuple[str, str]) -> None:
    x_event_signals[event] = mapping


def get_x_event_signals(event: int) -> Tuple[str, str] | None:
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


cdef dict parse_GenericEvent(Display *d, XEvent *e):
    cdef int etype = e.xcookie.extension
    cdef str event_type = x_event_type_names.get(etype, "") or str(etype)
    if etype == GenericEvent:
        log.warn("Warning: GenericEvent extension type is invalid")
        return {}
    if etype < 0 or etype >= MAX_XEVENTS:
        log.warn("Warning: event type %i out of range", etype)
        return None
    cdef PARSE_XEVENT parser = parsers[etype]
    if parser is NULL:
        log("no parser for generic event %s/%s", event_type, etype)
        return {}
    return parser(d, e)


cdef dict parse_MapRequest(Display *d, XEvent *e):
    return {
        "window": e.xmaprequest.window,
    }


cdef dict parse_ConfigureRequest(Display *d, XEvent *e):
    cdef XConfigureRequestEvent xconfigurerequest = e.xconfigurerequest
    return {
        "window": xconfigurerequest.window,
        "x": xconfigurerequest.x,
        "y": xconfigurerequest.y,
        "width": xconfigurerequest.width,
        "height": xconfigurerequest.height,
        "border_width": xconfigurerequest.border_width,
        # In principle there are two cases here: .above is
        # XNone (i.e. not specified in the original request),
        # or .above is an invalid window (i.e. it was
        # specified by the client, but it specified something
        # weird).  I don't see any reason to handle these
        # differently, though.
        "above": xconfigurerequest.above,
        "detail": xconfigurerequest.detail,
        "value_mask": xconfigurerequest.value_mask,
    }


cdef dict parse_SelectionRequest(Display *d, XEvent *e):
    cdef XSelectionRequestEvent * selectionrequest_e = <XSelectionRequestEvent*> e
    return {
        "window": selectionrequest_e.owner,
        "requestor": selectionrequest_e.requestor,
        "selection": atom_str(d, selectionrequest_e.selection),
        "target": atom_str(d, selectionrequest_e.target),
        "property": atom_str(d, selectionrequest_e.property),
        "time": int(selectionrequest_e.time),
    }


cdef dict parse_SelectionClear(Display *d, XEvent *e):
    cdef XSelectionClearEvent * selectionclear_e = <XSelectionClearEvent*> e
    return {
        "window": selectionclear_e.window,
        "selection": atom_str(d, selectionclear_e.selection),
        "time": int(selectionclear_e.time),
    }


cdef dict parse_SelectionNotify(Display *d, XEvent *e):
    cdef XSelectionEvent * selection_e = <XSelectionEvent*> e
    return {
        "requestor": selection_e.requestor,
        "selection": atom_str(d, selection_e.selection),
        "target": atom_str(d, selection_e.target),
        "property": atom_str(d, selection_e.property),
        "time": int(selection_e.time),
    }


cdef dict parse_ResizeRequest(Display *d, XEvent *e):
    return {
        "window": e.xresizerequest.window,
        "width": e.xresizerequest.width,
        "height": e.xresizerequest.height,
    }


cdef dict _parse_Focus(Display *d, XEvent *e):
    return {
        "window": e.xfocus.window,
        "mode": e.xfocus.mode,
        "detail": e.xfocus.detail,
    }


cdef dict parse_FocusIn(Display *d, XEvent *e):
    return _parse_Focus(d, e)


cdef dict parse_FocusOut(Display *d, XEvent *e):
    return _parse_Focus(d, e)


cdef object _parse_EnterLeave(Display *d, XEvent *e):
    cdef XCrossingEvent * crossing_e = <XCrossingEvent*> e
    return {
        "window": crossing_e.window,
        "root": crossing_e.root,
        "subwindow": crossing_e.subwindow,
        "mode": crossing_e.mode,
        "detail": crossing_e.detail,
        "focus": bool(crossing_e.focus),
        "state": crossing_e.state,
    }


cdef dict parse_EnterNotify(Display *d, XEvent *e):
    return _parse_EnterLeave(d, e)


cdef dict parse_LeaveNotify(Display *d, XEvent *e):
    return _parse_EnterLeave(d, e)


cdef dict parse_CreateNotify(Display *d, XEvent *e):
    return {
        "window": e.xcreatewindow.window,
        "width": e.xcreatewindow.width,
        "height": e.xcreatewindow.height,
    }


cdef dict parse_MapNotify(Display *d, XEvent *e):
    return {
        "window": e.xmap.window,
        "override_redirect": bool(e.xmap.override_redirect),
    }


cdef dict parse_UnmapNotify(Display *d, XEvent *e):
    return {
        "window": e.xunmap.window,
        "from_configure": bool(e.xunmap.from_configure),
    }


cdef dict parse_DestroyNotify(Display *d, XEvent *e):
    return {
        "window": e.xdestroywindow.window,
    }


cdef dict parse_PropertyNotify(Display *d, XEvent *e):
    return {
        "window": e.xany.window,
        "atom": atom_str(d, e.xproperty.atom),
        "time": e.xproperty.time,
    }


cdef dict parse_ConfigureNotify(Display *d, XEvent *e):
    return {
        "window": e.xconfigure.window,
        "x": e.xconfigure.x,
        "y": e.xconfigure.y,
        "width": e.xconfigure.width,
        "height": e.xconfigure.height,
        "border_width": e.xconfigure.border_width,
        "above": e.xconfigure.above,
        "override_redirect": bool(e.xconfigure.override_redirect),
    }


cdef dict parse_CirculateNotify(Display *d, XEvent *e):
    return {
        "window": e.xany.window,
    }


cdef dict parse_ReparentNotify(Display *d, XEvent *e):
    return {
        "window": e.xreparent.window,
        "parent": e.xreparent.parent,
        "x": e.xreparent.x,
        "y": e.xreparent.y,
    }


cdef dict parse_KeyPress(Display *d, XEvent *e):
    return {
        "window": e.xany.window,
        "hardware_keycode": e.xkey.keycode,
        "state": e.xkey.state,
    }


cdef dict parse_MotionNotify(Display *d, XEvent *e):
    return {
        "window": e.xmotion.window,
        "root": e.xmotion.root,
        "subwindow": e.xmotion.subwindow,
        "time": e.xmotion.time,
        "x": e.xmotion.x,
        "y": e.xmotion.y,
        "x_root": e.xmotion.x_root,
        "y_root": e.xmotion.y_root,
        "state": e.xmotion.state,
        "is_hint": e.xmotion.is_hint != NotifyNormal,
        #pyev.same_screen = bool(e.xmotion.same_screen),
    }


cdef dict parse_ClientMessage(Display *d, XEvent *e):
    if int(e.xclient.message_type) > 2**32:
        log.warn("Warning: Xlib claims that this ClientEvent's 32-bit")
        log.warn(f" message_type is {e.xclient.message_type}.")
        log.warn(" note that this is >2^32.")
        log.warn(" this makes no sense, so I'm ignoring it")
        return {}
    cdef unsigned int format = e.xclient.format
    cdef str message_type = atom_str(d, e.xclient.message_type)
    pieces: list[int] = []
    if format == 32:
        for i in range(5):
            # Mask with 0xffffffff to prevent sign-extension on
            # architectures where Python's int is 64-bits.
            pieces.append(int(e.xclient.data.l[i]) & 0xffffffff)
    elif format == 16:
        for i in range(10):
            pieces.append(int(e.xclient.data.s[i]))
    elif format == 8:
        for i in range(20):
            pieces.append(int(e.xclient.data.b[i]))
    else:
        log.warn(f"Warning: ignoring ClientMessage {message_type!r} with format={format}")
        return {}
    return {
        "window": e.xany.window,
        "message_type": message_type,
        "format": format,
        "data": tuple(pieces),
    }


cdef object parse_xevent(Display *d, XEvent *e):
    cdef int etype = e.type
    global x_event_type_names, x_event_signals
    cdef str event_type = x_event_type_names.get(etype, "") or str(etype)
    if e.xany.send_event and etype not in (ClientMessage, UnmapNotify):
        log("parse_xevent ignoring %s send_event", event_type)
        return None

    cdef object event_args = x_event_signals.get(etype)
    if not event_args:
        log("no signal handler for %s (%i)", event_type, etype)
        return None

    if etype < 0 or etype >= MAX_XEVENTS:
        log.warn("Warning: event type %i out of range", etype)
        return None

    log("parse_xevent event=%s/%s window=%#x", event_args, event_type, e.xany.window)
    cdef PARSE_XEVENT parser = parsers[etype]
    if parser is NULL:
        log.warn("no parser for %s/%s", event_type, etype)
        return None

    attrs = parser(d, e)
    if not attrs:
        return None

    cdef object pyev = X11Event(etype, event_type, bool(e.xany.send_event), e.xany.serial, e.xany.window)
    for k, v in attrs.items():
        setattr(pyev, k, v)
    return pyev
