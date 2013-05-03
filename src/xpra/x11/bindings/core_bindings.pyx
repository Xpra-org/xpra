# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time

from xpra.util import dump_exc, AdHocStruct
from xpra.log import Logger
log = Logger("xpra.x11.bindings.core_bindings")


###################################
# Headers, python magic
###################################
cdef extern from "stdlib.h":
    void* malloc(size_t __size)
    void free(void* mem)

cdef extern from "X11/Xutil.h":
    pass

cdef extern from "Python.h":
    object PyString_FromStringAndSize(char * s, int len)
    ctypedef int Py_ssize_t
    int PyObject_AsWriteBuffer(object obj,
                               void ** buffer,
                               Py_ssize_t * buffer_len) except -1
    int PyObject_AsReadBuffer(object obj,
                              void ** buffer,
                              Py_ssize_t * buffer_len) except -1


######
# Xlib primitives and constants
######

include "constants.pxi"
ctypedef unsigned long CARD32

cdef extern from "X11/Xlib.h":
    ctypedef struct Display:
        pass
    # To make it easier to translate stuff in the X header files into
    # appropriate pyrex declarations, without having to untangle the typedefs
    # over and over again, here are some convenience typedefs.  (Yes, CARD32
    # really is 64 bits on 64-bit systems.  Why?  I have no idea.)
    ctypedef CARD32 XID

    ctypedef int Bool
    ctypedef int Status
    ctypedef CARD32 Atom

    Atom XInternAtom(Display * display, char * atom_name, Bool only_if_exists)

    int XFree(void * data)

    void XSync(Display * display, Bool discard)

    void XGetErrorText(Display * display, int code, char * buffer_return, int length)


from display_source cimport get_display
from display_source import get_display_name

cdef class X11CoreBindings:

    def __cinit__(self):
        self.display = get_display()
        assert self.display!=NULL, "display is not set!"
        dn = get_display_name()
        self.display_name = dn

    cdef get_xatom(self, str_or_int):
        """Returns the X atom corresponding to the given Python string or Python
        integer (assumed to already be an X atom)."""
        cdef char* string
        if isinstance(str_or_int, (int, long)):
            return <Atom> str_or_int
        string = str_or_int
        return XInternAtom(self.display, string, False)

    def get_error_text(self, code):
        if type(code)!=int:
            return code
        cdef char[128] buffer
        XGetErrorText(self.display, code, buffer, 128)
        return str(buffer[:128])

    def XSync(self, discard=False):
        XSync(self.display, discard)
