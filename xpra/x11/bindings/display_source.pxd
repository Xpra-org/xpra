# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

cdef extern from "X11/Xlib.h":
    ctypedef struct Display:
        pass

cdef Display* get_display() noexcept
cdef int set_display(Display *d) except 1
