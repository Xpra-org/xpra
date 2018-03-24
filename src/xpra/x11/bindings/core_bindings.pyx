# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: auto_pickle=False
from __future__ import absolute_import

import os
import time

from xpra.util import dump_exc, envbool
from xpra.os_util import strtobytes
from xpra.log import Logger
log = Logger("x11", "bindings", "core")


include "constants.pxi"

###################################
# Headers, python magic
###################################
cdef extern from "X11/Xutil.h":
    pass

######
# Xlib primitives and constants
######

cdef extern from "X11/Xlib.h":
    ctypedef struct Display:
        pass
    ctypedef CARD32 Time
    ctypedef int Bool

    Atom XInternAtom(Display * display, char * atom_name, Bool only_if_exists)
    char *XGetAtomName(Display *display, Atom atom)

    int XFree(void * data)

    void XGetErrorText(Display * display, int code, char * buffer_return, int length)

    int XUngrabKeyboard(Display * display, Time t)
    int XUngrabPointer(Display * display, Time t)

    int *XSynchronize(Display *display, Bool onoff)


from xpra.x11.bindings.display_source cimport get_display
from xpra.x11.bindings.display_source import get_display_name

cdef _X11CoreBindings singleton = None
def X11CoreBindings():
    global singleton
    if singleton is None:
        singleton = _X11CoreBindings()
    return singleton

cdef class _X11CoreBindings:

    def __cinit__(self):
        self.display = get_display()
        assert self.display!=NULL, "display is not set!"
        dn = get_display_name()
        bstr = strtobytes(dn)
        self.display_name = bstr
        if envbool("XPRA_X_SYNC", False):
            XSynchronize(self.display, True)

    def get_display_name(self):
        return self.display_name

    def __repr__(self):
        return "X11CoreBindings(%s)" % self.display_name

    cdef Atom xatom(self, str_or_int):
        """Returns the X atom corresponding to the given Python string or Python
        integer (assumed to already be an X atom)."""
        cdef char* string
        if isinstance(str_or_int, (int, long)):
            return <Atom> str_or_int
        bstr = strtobytes(str_or_int)
        string = bstr
        assert self.display!=NULL, "display is closed"
        return XInternAtom(self.display, string, False)

    def get_xatom(self, str_or_int):
        return self.xatom(str_or_int)

    def XGetAtomName(self, Atom atom):
        v = XGetAtomName(self.display, atom)
        return v[:]

    def get_error_text(self, code):
        assert self.display!=NULL, "display is closed"
        if type(code)!=int:
            return code
        cdef char[128] buffer
        XGetErrorText(self.display, code, buffer, 128)
        return str(buffer[:128])

    def UngrabKeyboard(self, time=CurrentTime):
        assert self.display!=NULL, "display is closed"
        return XUngrabKeyboard(self.display, time)

    def UngrabPointer(self, time=CurrentTime):
        assert self.display!=NULL, "display is closed"
        return XUngrabPointer(self.display, time)
