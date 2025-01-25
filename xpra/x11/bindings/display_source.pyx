# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


# Sometimes we want to open the X11 display with XOpenDisplay,
# other times we may get an existing "Display" pointer from
# somewhere else, so we need this file to hide that...
# (we can't just pass pointers around easily with Python/Cython)

from libc.stdint cimport uintptr_t   # pylint: disable=syntax-error
from xpra.x11.bindings.xlib cimport Display

cdef Display *display = NULL
display_name = ""


cdef Display* get_display() noexcept:
    return display


def get_display_ptr() -> long:
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
