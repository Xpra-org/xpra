# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

cdef extern from "gtk-2.0/gdk/gdktypes.h":
    ctypedef struct cGdkDisplay "GdkDisplay":
        pass
    
    ctypedef struct _GdkAtom:
        pass
    ctypedef _GdkAtom* GdkAtom

cdef extern from "glib-2.0/glib-object.h":
    ctypedef struct cGObject "GObject":
        pass

cdef object wrap(cGObject * contents)
cdef cGObject * unwrap(box, pyclass) except? NULL

cpdef get_display_for(obj)
cdef cGdkDisplay * get_raw_display_for(obj) except? NULL
cdef GdkAtom get_raw_atom_for(obj) except? NULL

cdef void * pyg_boxed_get(v)

#def sanitize_gtkselectiondata(obj)
#def calc_constrained_size(int width, int height, object hints):
