# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from __future__ import absolute_import


from libc.stdint cimport uintptr_t

from xpra.log import Logger
log = Logger("bindings", "gtk")


import gi
gi.require_version('Gdk', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gdk                   #@UnresolvedImport
from gi.repository import Gtk                   #@UnresolvedImport
from gi.repository import GObject               #@UnresolvedImport


cdef extern from "gtk-3.0/gdk/gdk.h":
    ctypedef struct GdkWindow:
        pass
    ctypedef struct GdkDisplay:
        pass

cdef extern from "glib-2.0/glib-object.h":
    ctypedef struct cGObject "GObject":
        pass

cdef extern from "pygobject-3.0/pygobject.h":
    cGObject *pygobject_get(object box)
    object pygobject_new(cGObject * contents)

    ctypedef void* gpointer
    ctypedef int GType
    ctypedef struct PyGBoxed:
        #PyObject_HEAD
        gpointer boxed
        GType gtype


def get_display_for(obj):
    if obj is None:
        raise TypeError("Cannot get a display: instance is None!")
    if isinstance(obj, Gdk.Display):
        return obj
    elif isinstance(obj, (Gdk.Window,
                          Gtk.Widget,
                          Gtk.Clipboard,
                          Gtk.SelectionData,
                          )):
        return obj.get_display()
    else:
        raise TypeError("Don't know how to get a display from %r" % (obj,))


cdef GdkDisplay * get_raw_display_for(obj) except? NULL:
    return <GdkDisplay*> unwrap(get_display_for(obj), Gdk.Display)


cdef object wrap(cGObject * contents):
    # Put a raw GObject* into a PyGObject wrapper.
    return pygobject_new(contents)


cdef cGObject *unwrap(box, pyclass) except? NULL:
    # Extract a raw GObject* from a PyGObject wrapper.
    assert issubclass(pyclass, GObject.GObject)
    if not isinstance(box, pyclass):
        raise TypeError("object %r is not a %r" % (box, pyclass))
    return pygobject_get(box)

cdef void * pyg_boxed_get(v):
    cdef PyGBoxed * pygboxed = <PyGBoxed *> v
    return <void *> pygboxed.boxed

cdef GdkWindow *get_gdkwindow(pywindow):
    return <GdkWindow*>unwrap(pywindow, Gdk.Window)
