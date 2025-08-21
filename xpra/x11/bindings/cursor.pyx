# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.x11.bindings.xlib cimport Display
from xpra.x11.bindings.core cimport X11CoreBindingsInstance, import_check


import_check("cursor")


cdef extern from "X11/Xcursor/Xcursor.h":
    int XcursorGetDefaultSize (Display *dpy)


cdef class X11CursorBindingsInstance(X11CoreBindingsInstance):

    def __repr__(self):
        return "X11CursorBindingsInstance(%s)" % self.display_name

    def get_default_cursor_size(self) -> int:
        return XcursorGetDefaultSize(self.display)

cdef X11CursorBindingsInstance singleton = None


def X11CursorBindings() -> X11CursorBindingsInstance:
    global singleton
    if singleton is None:
        singleton = X11CursorBindingsInstance()
    return singleton
