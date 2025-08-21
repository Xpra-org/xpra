# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.x11.bindings.xlib cimport Display, Window, Pixmap, Bool, Status
from xpra.x11.bindings.core cimport X11CoreBindingsInstance, import_check

from xpra.log import Logger

import_check("composite")

log = Logger("x11", "bindings", "composite")


cdef extern from "X11/extensions/Xcomposite.h":
    unsigned int CompositeRedirectManual
    unsigned int CompositeRedirectAutomatic

    Bool XCompositeQueryExtension(Display *, int *, int *)
    Status XCompositeQueryVersion(Display *, int * major, int * minor)
    void XCompositeRedirectWindow(Display *, Window, int mode)
    void XCompositeRedirectSubwindows(Display *, Window, int mode)
    void XCompositeUnredirectWindow(Display *, Window, int mode)
    void XCompositeUnredirectSubwindows(Display *, Window, int mode)
    Window XCompositeGetOverlayWindow(Display *dpy, Window window)
    void XCompositeReleaseOverlayWindow(Display *dpy, Window window)
    Pixmap XCompositeNameWindowPixmap(Display *xdisplay, Window xwindow)


cdef class XCompositeBindingsInstance(X11CoreBindingsInstance):

    def ensure_XComposite_support(self) -> None:
        # We need NameWindowPixmap, but we don't need the overlay window
        # (v0.3) or the special manual-redirect clipping semantics (v0.4).
        cdef int event_base = 0, ignored = 0
        if not XCompositeQueryExtension(self.display, &event_base, &ignored):
            raise ValueError("X11 Composite extension is not available")

        cdef int major = 0, minor = 0
        if XCompositeQueryVersion(self.display, &major, &minor):
            log("found X11 Composite extension version %i.%i", major, minor)
            if (major, minor) < (0, 2):
                raise ValueError("Composite extension v%i.%i is too old" % (major, minor))

    def hasXComposite(self) -> bool:
        try:
            self.ensure_XComposite_support()
            return True
        except Exception as e:
            log.error("%s", e)
        return False

    def XCompositeRedirectWindow(self, Window xwindow) -> None:
        self.context_check("XCompositeRedirectWindow")
        XCompositeRedirectWindow(self.display, xwindow, CompositeRedirectManual)

    def XCompositeRedirectSubwindows(self, Window xwindow) -> None:
        self.context_check("XCompositeRedirectSubwindows")
        XCompositeRedirectSubwindows(self.display, xwindow, CompositeRedirectManual)

    def XCompositeUnredirectWindow(self, Window xwindow) -> None:
        self.context_check("XCompositeUnredirectWindow")
        XCompositeUnredirectWindow(self.display, xwindow, CompositeRedirectManual)

    def XCompositeUnredirectSubwindows(self, Window xwindow) -> None:
        self.context_check("XCompositeUnredirectSubwindows")
        XCompositeUnredirectSubwindows(self.display, xwindow, CompositeRedirectManual)

    def XCompositeGetOverlayWindow(self, Window window) -> Window:
        self.context_check("XCompositeGetOverlayWindow")
        return XCompositeGetOverlayWindow(self.display, window)

    def XCompositeReleaseOverlayWindow(self, Window window) -> None:
        self.context_check("XCompositeReleaseOverlayWindow")
        XCompositeReleaseOverlayWindow(self.display, window)

    def XCompositeNameWindowPixmap(self, Window xwindow) -> Pixmap:
        self.context_check("XCompositeNameWindowPixmap")
        return XCompositeNameWindowPixmap(self.display, xwindow)


cdef XCompositeBindingsInstance singleton = None


def XCompositeBindings() -> XCompositeBindingsInstance:
    global singleton
    if singleton is None:
        singleton = XCompositeBindingsInstance()
    return singleton
