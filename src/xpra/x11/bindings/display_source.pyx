# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


# Sometimes we want to open the X11 display with XOpenDisplay,
# other times we may get an existing "Display" pointer from
# somewhere else, so we need this file to hide that...
# (we can't just pass pointers around easily with Python/Cython)

cdef extern from "X11/Xlib.h":
    ctypedef struct Display:
        pass

cdef Display *display
display = NULL
display_name = ""

cdef Display* get_display():
    return display

cdef void set_display(Display *d):
    global display
    if display!=NULL and d!=NULL:
        raise Exception("display is already set")
    display = d


def clear_display():
    global display
    display = NULL

def get_display_name():
    return display_name

def set_display_name(name):
    global display_name
    display_name = name
