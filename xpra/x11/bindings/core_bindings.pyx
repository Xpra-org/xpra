# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.x11.bindings.xlib cimport (
    Display, Time, Bool, Status,
    XInternAtom, XInternAtoms,
    XGetAtomName,
    XFree,
    XGetErrorText,
    XUngrabKeyboard, XUngrabPointer,
    XSynchronize, XSync, XFlush,
    CurrentTime, MappingBusy, GrabModeAsync, AnyModifier,
    PropModeReplace,
    )
from libc.stdlib cimport malloc, free       #pylint: disable=syntax-error
from libc.stdint cimport uintptr_t

from xpra.util import envbool
from xpra.os_util import strtobytes, is_X11
from xpra.log import Logger
log = Logger("x11", "bindings", "core")

from xpra.x11.bindings.display_source cimport get_display
from xpra.x11.bindings.display_source import get_display_name

cdef X11CoreBindingsInstance singleton = None
def X11CoreBindings():
    global singleton
    if singleton is None:
        singleton = X11CoreBindingsInstance()
    return singleton

def noop(*args):
    pass

cdef object context_check = noop
def set_context_check(fn):
    global context_check
    context_check = fn


cdef class X11CoreBindingsInstance:

    def __cinit__(self):
        assert is_X11(), "cannot load X11 bindings with wayland under python3 / GTK3"
        self.display = get_display()
        assert self.display!=NULL, "display is not set!"
        dn = get_display_name()
        bstr = strtobytes(dn)
        self.display_name = bstr
        self.XSynchronize(envbool("XPRA_X_SYNC", False))

    def XSynchronize(self, enable : bool):
        XSynchronize(self.display, enable)

    def XSync(self, discard=False):
        XSync(self.display, discard)

    def XFlush(self):
        XFlush(self.display)

    def context_check(self):
        global context_check
        context_check()

    def get_display_name(self):
        return self.display_name

    def __repr__(self):
        return "X11CoreBindings(%s)" % self.display_name

    cdef Atom xatom(self, str_or_int):
        """Returns the X atom corresponding to the given Python string or Python
        integer (assumed to already be an X atom)."""
        self.context_check()
        if isinstance(str_or_int, (int, long)):
            return <Atom> str_or_int
        bstr = strtobytes(str_or_int)
        cdef char* string = bstr
        assert self.display!=NULL, "display is closed"
        return XInternAtom(self.display, string, False)

    def intern_atoms(self, atom_names):
        cdef int count = len(atom_names)
        cdef char** names = <char **> malloc(sizeof(uintptr_t)*(count+1))
        assert names!=NULL
        cdef Atom* atoms_return = <Atom*> malloc(sizeof(Atom)*(count+1))
        assert atoms_return!=NULL
        from ctypes import create_string_buffer, addressof
        str_names = [create_string_buffer(strtobytes(x)) for x in atom_names]
        cdef uintptr_t ptr
        for i, x in enumerate(str_names):
            ptr = addressof(x)
            names[i] = <char*> ptr
        cdef Status s = XInternAtoms(self.display, names, count, 0, atoms_return)
        free(names)
        free(atoms_return)
        assert s!=0, "failed to intern some atoms"

    def get_xatom(self, str_or_int):
        return self.xatom(str_or_int)

    def XGetAtomName(self, Atom atom):
        self.context_check()
        cdef char *v = XGetAtomName(self.display, atom)
        if v==NULL:
            return None
        r = v[:]
        XFree(v)
        return r

    def get_error_text(self, code):
        assert self.display!=NULL, "display is closed"
        if type(code)!=int:
            return code
        cdef char[128] buffer
        XGetErrorText(self.display, code, buffer, 128)
        return (bytes(buffer[:128]).split(b"\0", 1)[0]).decode("latin1")

    def UngrabKeyboard(self, time=CurrentTime):
        assert self.display!=NULL, "display is closed"
        return XUngrabKeyboard(self.display, time)

    def UngrabPointer(self, time=CurrentTime):
        assert self.display!=NULL, "display is closed"
        return XUngrabPointer(self.display, time)
