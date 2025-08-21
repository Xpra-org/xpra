# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.x11.bindings.xlib cimport Display, Atom

cdef class X11CoreBindingsInstance:
    cdef Display * display
    cdef object display_name
    cdef Atom xatom(self, str_or_int)
    cdef Atom str_to_atom(self, atomstr)
#    def get_error_text(self, code)

cdef void import_check(modname)
