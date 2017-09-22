# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


# Sometimes we want to open the X11 display with XOpenDisplay,
# other times we may get an existing "Display" pointer from
# somewhere else, so we need this file to hide that...
# (we can't just pass pointers around easily with Python/Cython)
from __future__ import absolute_import

from libc.stdint cimport uintptr_t

cdef extern from "X11/Xlib.h":
    ctypedef struct Display:
        pass

cdef Display *display
display = NULL
display_name = ""

cdef Display* get_display():
    return display

def get_display_ptr():
    return int(<uintptr_t> display)

cdef int set_display(Display *d) except 1:
    global display
    if display!=NULL and d!=NULL and d!=display:
        raise Exception("display is already set")
    display = d
    return 0


def clear_display():
    global display
    display = NULL

def get_display_name():
    return display_name

def set_display_name(name):
    global display_name
    display_name = name
