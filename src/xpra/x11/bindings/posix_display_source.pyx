# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


# This module can be used to open the local $DISPLAY and hook it into the X11 bindings

import os
from xpra.os_util import strtobytes
from xpra.x11.bindings.display_source cimport set_display, get_display
from xpra.x11.bindings.display_source import set_display_name
from libc.stdint cimport uintptr_t

cdef extern from "X11/Xlib.h":
    ctypedef struct Display:
        pass
    Display *XOpenDisplay(char *display_name)
    int XCloseDisplay(Display *display)

def init_posix_display_source():
    display_name = os.environ.get("DISPLAY")
    if not display_name:
        raise Exception("cannot open display, the environment variable DISPLAY is not set!")
    return do_init_posix_display_source(display_name)

cdef do_init_posix_display_source(display_name):
    if not display_name:
        raise Exception("display name not provided")
    cdef Display * display = XOpenDisplay(strtobytes(display_name))
    if display==NULL:
        raise Exception("failed to open X11 display '%s'" % display_name)
    set_display(display)
    set_display_name(display_name)
    return <uintptr_t> display

def close_display_source(uintptr_t ptr):
    assert ptr!=0, "invalid NULL display pointer"
    cdef Display * display = <Display *> ptr
    cdef int v = XCloseDisplay(display)
    set_display(NULL)
    set_display_name("CLOSED")
    return v


class X11DisplayContext(object):
    """
        Ensures that there is an X11 display source available
        so the X11 bindings will work as expected.
        If one does not exist yet,
        a temporary posix display source will be used.
    """

    def __init__(self):
        self.close = False
        self.display = 0

    def __enter__(self):
        if get_display()==NULL:
            self.close = True
            self.display = init_posix_display_source()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        d = self.display
        if d and self.close:
            self.display = 0
            self.close = False
            close_display_source(d)

    def __repr__(self):
        return "X11DisplayContext(%#x)" % self.display
