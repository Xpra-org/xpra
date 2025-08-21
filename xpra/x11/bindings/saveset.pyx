# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.x11.bindings.xlib cimport XAddToSaveSet, XRemoveFromSaveSet, Window
from xpra.x11.bindings.core cimport X11CoreBindingsInstance, import_check

import_check("saveset")

cdef class X11SaveSetBindingsInstance(X11CoreBindingsInstance):

    def XAddToSaveSet(self, Window xwindow) -> None:
        self.context_check("XAddToSaveSet")
        XAddToSaveSet(self.display, xwindow)

    def XRemoveFromSaveSet(self, Window xwindow) -> None:
        self.context_check("XRemoveFromSaveSet")
        XRemoveFromSaveSet(self.display, xwindow)


cdef X11SaveSetBindingsInstance singleton = None


def XSaveSetBindings() -> X11SaveSetBindingsInstance:
    global singleton
    if singleton is None:
        singleton = X11SaveSetBindingsInstance()
    return singleton
