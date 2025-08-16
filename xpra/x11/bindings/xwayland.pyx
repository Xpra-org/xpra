# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from io import StringIO
from contextlib import redirect_stderr
from xpra.x11.bindings.xlib cimport (
    Success,
    Display, Window, Atom, Status,
    XInternAtom,
    XOpenDisplay, XCloseDisplay,
    XQueryExtension,
    XGetWindowProperty, XDefaultRootWindow,
)
from libc.stdint cimport uintptr_t
from xpra.log import Logger

log = Logger("x11")

DEF XNone = 0


def isX11(display_name: str=os.environ.get("DISPLAY", "")) -> bool:
    b = display_name.encode()
    cdef char* display = b
    cdef Display *d = NULL
    with redirect_stderr(StringIO()) as f:
        d = XOpenDisplay(display)
    if not d:
        log(f"isX11({display_name}) cannot open display: %s", f.getvalue())
        return False
    XCloseDisplay(d)
    return True


def isxwayland(display_name: str=os.environ.get("DISPLAY", "")) -> bool:
    b = display_name.encode()
    cdef char* display = b
    cdef Display *d = NULL
    with redirect_stderr(StringIO()) as f:
        d = XOpenDisplay(display)
    if not d:
        log(f"isxwayland({display_name}) cannot open display: %s", f.getvalue())
        return False
    log("isxwayland(%s) opened display %#x", display_name, <uintptr_t> d)
    cdef int opcode, event, error
    try:
        #the easy way:
        if XQueryExtension(d, "XWAYLAND", &opcode, &event, &error):
            log(f"isxwayland({display_name}) XWAYLAND extension found")
            return True
        #surely a vfb is not wayland?
        if get_xstring(d, "VFB_IDENT"):
            log(f"isxwayland({display_name}) VFB_IDENT found")
            return False
        # this can go wrong...
        try:
            from xpra.x11.bindings.randr import get_monitor_properties
        except ImportError:
            log(f"isxwayland({display_name}) RandRBindings not available")
            return False
        props = get_monitor_properties(<uintptr_t> d)
        log(f"isxwayland({display_name}) monitor properties={props}")
        for mprops in props.values():
            if mprops.get("name", "").startswith("XWAYLAND"):
                log(f"isxwayland({display_name}) found XWAYLAND monitor: {mprops}")
                return True
        return False
    finally:
        XCloseDisplay(d)


cdef Atom intern_atom(Display *display, name: str):
    b = name.encode()
    return XInternAtom(display, b, True)


cdef str get_xstring(Display *display, name="XPRA_SERVER_UUID", prop_type="STRING"):
    cdef Atom xactual_type = <Atom> 0
    cdef int actual_format = 0
    cdef unsigned long nitems = 0, bytes_after = 0
    cdef unsigned char * prop_data = <unsigned char*> 0
    cdef Atom xtype = 0, prop = 0

    def fail(message):
        #print(message)
        return ""

    xtype = intern_atom(display, prop_type)
    if xtype==0:
        #the property cannot exist if the type is not defined
        return fail(f"Atom {prop_type} does not exist")
    prop = intern_atom(display, name)
    if prop==0:
        #the atom for the name does not exist so the property cannot exist:
        return fail(f"Atom {name} does not exist")
    cdef Window root = XDefaultRootWindow(display)
    cdef int buffer_size = 128
    cdef Status status = XGetWindowProperty(display, root, prop,
                                            0,
                                            buffer_size // 4,
                                            False,
                                            xtype, &xactual_type,
                                            &actual_format, &nitems, &bytes_after, &prop_data)
    if status != Success:
        return fail(f"XGetWindowProperty failed")
    if xactual_type == XNone:
        return fail(f"no actual type")
    if xtype != xactual_type:
        return fail(f"actual type differs")
    if nitems==0:
        return fail(f"no data")
    if bytes_after:
        return fail(f"more data than expected")
    if actual_format == 8:
        bytes_per_item = 1
    elif actual_format == 16:
        bytes_per_item = sizeof(short)
    elif actual_format == 32:
        bytes_per_item = sizeof(long)
    else:
        raise RuntimeError(f"unexpected format value: {actual_format}")
    cdef int nbytes = bytes_per_item * nitems
    data = (<char *> prop_data)[:nbytes]
    return data.decode("latin1")
