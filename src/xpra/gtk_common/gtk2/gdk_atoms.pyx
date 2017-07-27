# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# cython code for manipulating GdkAtoms
# split from bindings.pyx as this needs to be built on win32 too
# and win32 does not have all the X11 stuff

#cython: wraparound=False

import gobject
import gtk
import gtk.gdk

from libc.stdint cimport uintptr_t

from xpra.log import Logger
log = Logger("gtk")

###################################
# Headers, python magic
###################################
# Serious black magic happens here (I owe these guys beers):
cdef extern from "pygobject.h":
    void pygobject_init(int req_major, int req_minor, int req_micro)
pygobject_init(-1, -1, -1)

cdef extern from "pygtk/pygtk.h":
    void init_pygtk()
init_pygtk()
# Now all the macros in those header files will work.

cdef extern from "Python.h":
    int PyObject_AsReadBuffer(object obj,
                              void ** buffer,
                              Py_ssize_t * buffer_len) except -1

###################################
# GObject
###################################
cdef extern from "gtk-2.0/gdk/gdktypes.h":
    ctypedef unsigned long GdkAtom
    GdkAtom GDK_NONE

cdef extern from "pygtk-2.0/pygtk/pygtk.h":
    # FIXME: this should have stricter type checking
    GdkAtom PyGdkAtom_Get(object)
    object PyGdkAtom_New(GdkAtom)


def gdk_atom_objects_from_gdk_atom_array(atom_string):
    # gdk_property_get auto-converts ATOM and ATOM_PAIR properties from a
    # string of marshalled X atoms to an array of GDK atoms. GDK atoms and X
    # atoms are both basically numeric values, but they are often *different*
    # numeric values. The GTK+ clipboard code uses gdk_property_get. To
    # interpret atoms when dealing with the clipboard, therefore, we need to
    # be able to take an array of GDK atom objects (integers) and figure out
    # what they mean.
    cdef const GdkAtom * array = <GdkAtom*> NULL
    cdef Py_ssize_t array_len_bytes = 0
    cdef long gdk_atom_value = 0
    assert PyObject_AsReadBuffer(atom_string, <const void**> &array, &array_len_bytes)==0
    array_len = array_len_bytes / sizeof(GdkAtom)
    objects = []
    for i in range(array_len):
        if array[i]==GDK_NONE:
            continue
        gdk_atom = PyGdkAtom_New(array[i])
        objects.append(gdk_atom)
    return objects

def gdk_atom_array_from_gdk_atom_objects(gdk_atom_objects):
    cdef GdkAtom c_gdk_atom
    cdef unsigned long gdk_atom_value
    atom_array = []
    for atom_object in gdk_atom_objects:
        c_gdk_atom = PyGdkAtom_Get(atom_object)
        if c_gdk_atom!=GDK_NONE:
            gdk_atom_value = <uintptr_t> c_gdk_atom
            atom_array.append(gdk_atom_value)
    return atom_array
