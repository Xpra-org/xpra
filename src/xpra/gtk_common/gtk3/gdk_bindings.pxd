# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

cdef extern from "gtk-3.0/gdk/gdk.h":
    ctypedef struct GdkDisplay:
        pass
    ctypedef struct GdkWindow:
        pass

cdef extern from "glib-2.0/glib-object.h":
    ctypedef struct cGObject "GObject":
        pass

cdef object wrap(cGObject * contents)
cdef cGObject *unwrap(box, pyclass) except? NULL
cdef void *pyg_boxed_get(v)

cdef GdkDisplay *get_raw_display_for(obj) except? NULL

cdef GdkWindow *get_gdkwindow(pywindow)
