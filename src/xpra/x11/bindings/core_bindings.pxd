# This file is part of Xpra.
# Copyright (C) 2013-2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


ctypedef unsigned long CARD32

cdef extern from "X11/Xlib.h":
    ctypedef struct Display:
        pass
    ctypedef CARD32 Atom

cdef class _X11CoreBindings:
    cdef Display * display
    cdef char * display_name
    cdef Atom xatom(self, str_or_int) except -1
#    def get_error_text(self, code)
