# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# cython code for manipulating GdkAtoms
from typing import List

from xpra.os_util import gi_import
from libc.stdint cimport uintptr_t   # pylint: disable=syntax-error

Gdk = gi_import("Gdk")


cdef extern from "Python.h":
    int PyObject_GetBuffer(object obj, Py_buffer *view, int flags)
    void PyBuffer_Release(Py_buffer *view)
    int PyBUF_ANY_CONTIGUOUS

cdef extern from "gtk-3.0/gdk/gdk.h":
    ctypedef void* GdkAtom
    GdkAtom GDK_NONE

cdef extern from "gtk-3.0/gdk/gdkproperty.h":
    ctypedef char gchar
    ctypedef int gint
    ctypedef gint gboolean
    gchar* gdk_atom_name(GdkAtom atom)
    GdkAtom gdk_atom_intern(const gchar *atom_name, gboolean only_if_exists)


def gdk_atom_objects_from_gdk_atom_array(atom_string) -> List[Gdk.Atom]:
    cdef Py_buffer py_buf
    if PyObject_GetBuffer(atom_string, &py_buf, PyBUF_ANY_CONTIGUOUS):
        raise ValueError(f"failed to read atom buffer of {type(atom_string)}")
    cdef unsigned int array_len = py_buf.len // sizeof(GdkAtom)
    objects = []
    cdef unsigned int i
    cdef const GdkAtom * array = <GdkAtom*> py_buf.buf
    cdef GdkAtom atom
    cdef gchar*  name
    for i in range(array_len):
        atom = array[i]
        if atom==GDK_NONE:
            continue
        #round-trip via the name,
        #inefficient but what other constructor is there?
        name = gdk_atom_name(atom)
        if name:
            str_name = name.decode("latin1")
            gdk_atom = Gdk.Atom.intern(str_name, False)
            objects.append(gdk_atom)
    PyBuffer_Release(&py_buf)
    return objects


def gdk_atom_array_from_atoms(atoms) -> List[int]:
    cdef GdkAtom gdk_atom
    cdef uintptr_t gdk_atom_value
    atom_array = []
    for atom in atoms:
        gdk_atom = gdk_atom_intern(atom, False)
        if gdk_atom!=GDK_NONE:
            gdk_atom_value = <uintptr_t> gdk_atom
            atom_array.append(gdk_atom_value)
    return atom_array
