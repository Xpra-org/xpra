# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from math import ceil, floor

from xpra.os_util import gi_import
from xpra.log import Logger
log = Logger("bindings", "gtk")

GObject = gi_import("GObject")
log(f"GObject={GObject}")

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


cdef object wrap(cGObject * contents):
    # Put a raw GObject* into a PyGObject wrapper.
    return pygobject_new(contents)


cdef cGObject *unwrap(box, pyclass) except? NULL:
    # Extract a raw GObject* from a PyGObject wrapper.
    assert issubclass(pyclass, GObject.GObject)
    if not isinstance(box, pyclass):
        raise TypeError("object %r is not a %r" % (box, pyclass))
    return pygobject_get(box)
