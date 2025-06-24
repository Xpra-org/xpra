# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable, Sequence

from xpra.x11.bindings.xlib cimport (
    Display, Time, Bool, Status, Atom,
    XInternAtom, XInternAtoms,
    XGetAtomName,
    XFree,
    XGetErrorText,
    XUngrabKeyboard, XUngrabPointer,
    XSynchronize, XSync, XFlush,
    CurrentTime,
    XDefaultRootWindow,
)
from libc.stdlib cimport malloc, free        # pylint: disable=syntax-error
from libc.stdint cimport uintptr_t

from xpra.util.env import envbool
from xpra.util.str_fn import strtobytes
from xpra.util.system import is_X11
from xpra.log import Logger
log = Logger("x11", "bindings", "core")

from xpra.x11.bindings.display_source cimport get_display
from xpra.x11.bindings.display_source import get_display_name


def noop(*args) -> None:
    pass


cdef object context_check = noop


def set_context_check(fn: Callable) -> None:
    global context_check
    context_check = fn


def call_context_check(*args) -> None:
    context_check(*args)


cdef class X11CoreBindingsInstance:

    def __cinit__(self):
        if not is_X11():
            raise RuntimeError("cannot load X11 bindings with wayland")
        self.display = get_display()
        if self.display == NULL:
            raise RuntimeError("X11 display is not set")
        bstr = get_display_name().encode("latin1")
        self.display_name = bstr
        self.XSynchronize(envbool("XPRA_X_SYNC", False))

    def XSynchronize(self, enable: bool) -> None:
        XSynchronize(self.display, enable)

    def XSync(self, discard=False) -> None:
        XSync(self.display, discard)

    def XFlush(self) -> None:
        XFlush(self.display)

    def context_check(self, *args) -> None:
        global context_check
        context_check(*args)

    def __repr__(self):
        return "X11CoreBindings(%s)" % self.display_name

    def get_root_xid(self) -> long:
        assert self.display
        return XDefaultRootWindow(self.display)

    cdef Atom str_to_atom(self, atomstr):
        """Returns the X atom corresponding to the given Python string or Python
        integer (assumed to already be an X atom)."""
        self.context_check("str_to_atom")
        bstr = strtobytes(atomstr)
        cdef char* string = bstr
        assert self.display!=NULL, "display is closed"
        return XInternAtom(self.display, string, False)

    cdef Atom xatom(self, str_or_int):
        """Returns the X atom corresponding to the given Python string or Python
        integer (assumed to already be an X atom)."""
        if isinstance(str_or_int, int):
            return <Atom> str_or_int
        return self.str_to_atom(str_or_int)

    def intern_atoms(self, atom_names: Sequence[str]) -> None:
        cdef int count = len(atom_names)
        cdef char** names = <char **> malloc(sizeof(uintptr_t)*(count+1))
        assert names!=NULL
        cdef Atom* atoms_return = <Atom*> malloc(sizeof(Atom)*(count+1))
        assert atoms_return!=NULL
        from ctypes import create_string_buffer, addressof
        str_names = [create_string_buffer(x.encode("latin1")) for x in atom_names]
        cdef uintptr_t ptr
        for i, x in enumerate(str_names):
            ptr = addressof(x)
            names[i] = <char*> ptr
        cdef Status s = XInternAtoms(self.display, names, count, 0, atoms_return)
        free(names)
        free(atoms_return)
        assert s!=0, "failed to intern some atoms"

    def get_xatom(self, str_or_int) -> Atom:
        return self.xatom(str_or_int)

    def XGetAtomName(self, Atom atom) -> bytes:
        self.context_check("XGetAtomName")
        cdef char *v = XGetAtomName(self.display, atom)
        if v == NULL:
            return b""
        r = v[:]
        XFree(v)
        return r

    def get_atom_name(self, Atom atom) -> str:
        bin_name = self.XGetAtomName(atom)
        return bin_name.decode("latin1")

    def get_error_text(self, code) -> str:
        if self.display == NULL:
            raise RuntimeError("display is closed")
        if not isinstance(code, int):
            return str(code)
        cdef char[128] buffer
        XGetErrorText(self.display, code, buffer, 128)
        return (bytes(buffer[:128]).split(b"\0", 1)[0]).decode("latin1")

    def UngrabKeyboard(self, Time time=CurrentTime) -> long:
        self.context_check("UngrabKeyboard")
        if self.display == NULL:
            raise RuntimeError("display is closed")
        return XUngrabKeyboard(self.display, time)

    def UngrabPointer(self, Time time=CurrentTime) -> long:
        self.context_check("UngrabPointer")
        if self.display == NULL:
            raise RuntimeError("display is closed")
        return XUngrabPointer(self.display, time)


cdef X11CoreBindingsInstance singleton = None


def X11CoreBindings() -> X11CoreBindingsInstance:
    global singleton
    if singleton is None:
        singleton = X11CoreBindingsInstance()
    return singleton
