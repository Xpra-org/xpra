# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010-2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


# This class simply opens the local $DISPLAY and hooks it into the bindings

import os
from xpra.os_util import strtobytes
from xpra.x11.bindings.display_source cimport set_display
from xpra.x11.bindings.display_source import set_display_name

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

def do_init_posix_display_source(display_name):
    if not display_name:
        raise Exception("display name not provided")
    cdef Display * display = XOpenDisplay(strtobytes(display_name))
    if display==NULL:
        raise Exception("failed to open X11 display '%s'" % display_name)
    set_display(display)
    set_display_name(display_name)
    return <unsigned long> display

def close_display_source(unsigned long ptr):
    assert ptr!=0, "invalid NULL display pointer"
    cdef Display * display = <Display *> ptr
    cdef int v = XCloseDisplay(display)
    set_display(NULL)
    set_display_name("CLOSED")
    return v
