# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


cdef extern from "X11/Xlib.h":
    ctypedef struct Display:
        pass

cdef class X11CoreBindings:
    cdef Display * display
    cdef char * display_name
    cdef get_xatom(self, str_or_int)
#    def get_error_text(self, code)
#    def XSync(self, discard=False):
