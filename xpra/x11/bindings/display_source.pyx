# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


# Sometimes we want to open the X11 display with XOpenDisplay,
# other times we may get an existing "Display" pointer from
# somewhere else, so we need this file to hide that...
# (we can't just pass pointers around easily with Python/Cython)

import os
import cython
from libc.stdint cimport uintptr_t
from xpra.x11.bindings.xlib cimport Display, XOpenDisplay, XCloseDisplay

cdef Display *display = NULL
cdef str display_name = ""


cdef Display* get_display() noexcept:
    return display


def get_display_ptr() -> cython.ulong:
    return int(<uintptr_t> display)


cdef int set_display(Display *d) except 1:
    global display
    if display!=NULL and d!=NULL and d!=display:
        raise RuntimeError("display is already set")
    display = d
    return 0


def clear_display() -> None:
    global display
    display = NULL


def get_display_name() -> str:
    return display_name


def set_display_name(name: str) -> None:
    global display_name
    display_name = name


def init_display_source() -> None:
    display = display_name or os.environ.get("DISPLAY", "")
    if not display:
        raise ValueError("cannot open display, the environment variable DISPLAY is not set!")
    return do_init_display_source(display)


cdef uintptr_t do_init_display_source(display_name: str):
    if not display_name:
        raise ValueError("display name not provided")
    bin_name = display_name.encode("latin1")
    cdef Display * display = XOpenDisplay(bin_name)
    if display==NULL:
        raise ValueError("failed to open X11 display '%s'" % display_name)
    set_display(display)
    set_display_name(display_name)

    return <uintptr_t> display


def close_display_source(uintptr_t ptr) -> int:
    assert ptr!=0, "invalid NULL display pointer"
    cdef Display * display = <Display *> ptr
    set_display(NULL)
    set_display_name("CLOSED")
    cdef int v = XCloseDisplay(display)
    return v


class X11DisplayContext:
    """
        Ensures that there is an X11 display source available
        so the X11 bindings will work as expected.
        If one does not exist yet,
        a temporary display source will be used.
    """

    def __init__(self, display_name=os.environ.get("DISPLAY", "")):
        self.close = False
        self.display_name = display_name
        self.display = 0
        self.saved_display = 0

    def __enter__(self):
        if get_display() == NULL:
            self.close = True
            self.saved_display = get_display_ptr()
            self.display = do_init_display_source(self.display_name)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        d = self.display
        if d and self.close:
            self.display = 0
            self.close = False
            close_display_source(d)
        if self.saved_display:
            set_display(<Display *> self.saved_display)
            self.saved_display = 0

    def __repr__(self):
        return "X11DisplayContext(%s @ %#x)" % (self.display_name, self.display)
