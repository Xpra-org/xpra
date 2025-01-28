# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# This module can be used to open the local $DISPLAY and hook it into the X11 bindings

import os
from xpra.x11.bindings.xlib cimport Display, XOpenDisplay, XCloseDisplay
from xpra.x11.bindings.display_source cimport set_display, get_display   # pylint: disable=syntax-error
from xpra.x11.bindings.display_source import set_display_name  # @UnresolvedImport
from libc.stdint cimport uintptr_t


def init_posix_display_source() -> None:
    display_name = os.environ.get("DISPLAY")
    if not display_name:
        raise ValueError("cannot open display, the environment variable DISPLAY is not set!")
    return do_init_posix_display_source(display_name)


cdef uintptr_t do_init_posix_display_source(display_name: str):
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
        a temporary posix display source will be used.
    """

    def __init__(self, display_name=os.environ.get("DISPLAY")):
        self.close = False
        self.display_name = display_name
        self.display = 0

    def __enter__(self):
        if get_display()==NULL:
            self.close = True
            self.display = do_init_posix_display_source(self.display_name)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        d = self.display
        if d and self.close:
            self.display = 0
            self.close = False
            close_display_source(d)

    def __repr__(self):
        return "X11DisplayContext(%s @ %#x)" % (self.display_name, self.display)
