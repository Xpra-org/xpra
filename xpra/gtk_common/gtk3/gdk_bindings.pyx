# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: language_level=3

from math import ceil, floor

from xpra.log import Logger
log = Logger("bindings", "gtk")


import gi
gi.require_version('Gdk', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gdk                   #@UnresolvedImport
from gi.repository import Gtk                   #@UnresolvedImport
from gi.repository import GObject               #@UnresolvedImport


cdef extern from "gtk-3.0/gdk/gdk.h":  #pylint: disable=syntax-error
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

def calc_constrained_size(int width, int height, object hints):
    if not hints:
        return width, height

    def getintpair(key, int dv1, int dv2):
        v = hints.get(key)
        if v:
            try:
                return int(v[0]), int(v[1])
            except (ValueError, IndexError):
                pass
        return dv1, dv2

    cdef int min_width, min_height
    cdef int max_width, max_height
    cdef int base_width, base_height
    cdef int e_width, e_height
    cdef int increment_x, increment_y

    min_width, min_height = getintpair("minimum-size", 0, 0)
    if min_width>0:
        width = max(min_width, width)
    if min_height>0:
        height = max(min_height, height)

    max_width, max_height = getintpair("maximum-size", 2**16-1, 2**16-1)
    if max_width>0:
        width = min(max_width, width)
    if max_height>0:
        height = max(min_height, height)

    base_width, base_height = getintpair("base-size", 0, 0)
    increment_x, increment_y = getintpair("increment", 0, 0)
    if increment_x:
        e_width = max(width-base_width, 0)
        width -= e_width%increment_x
    if increment_y:
        e_height = max(height-base_height, 0)
        height -= e_height%increment_y

    cdef double min_aspect, max_aspect
    if "min_aspect" in hints:
        min_aspect = hints.get("min_aspect")
        assert min_aspect>0
        if width/height<min_aspect:
            height = ceil(width*min_aspect)
            if increment_y>1 or base_height>0:
                e_height = max(height-base_height, 0)
                height += increment_y-(e_height%increment_y)
    if "max_aspect" in hints:
        max_aspect = hints.get("max_aspect")
        assert max_aspect>0
        if width/height>max_aspect:
            height = floor(width*max_aspect)
            if increment_y>1 or base_height>0:
                e_height = max(height-base_height, 0)
                height = max(1, height-e_height%increment_y)
    return width, height
