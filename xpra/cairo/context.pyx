# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Creates a cairo.XlibSurface (and therefore a cairo.Context) directly from
# an X11 window XID, without going through GDK.

from xpra.x11.bindings.display_source cimport get_display
from xpra.x11.bindings.xlib cimport Display, Window, Status

cdef extern from "X11/Xlib.h":
    ctypedef struct Visual:
        pass
    ctypedef struct XWindowAttributes:
        int     width
        int     height
        Visual *visual
    Status XGetWindowAttributes(Display *dpy, Window w, XWindowAttributes *attrs_return)

cdef extern from "cairo/cairo.h":
    ctypedef struct cairo_surface_t:
        pass

cdef extern from "cairo/cairo-xlib.h":
    cairo_surface_t *cairo_xlib_surface_create(
        Display *dpy, Window drawable, Visual *visual, int width, int height)

# Use a verbatim C block so the PycairoSurface_FromSurface macro expands correctly.
# Pycairo_CAPI is a per-translation-unit static that must be initialised via
# Pycairo_IMPORT before the macro can be used.
cdef extern from *:
    """
    #include <pycairo/py3cairo.h>
    static PyObject* surface_from_xlib(cairo_surface_t *s) {
        if (!Pycairo_CAPI)
            import_cairo();
        return PycairoSurface_FromSurface(s, NULL);
    }
    """
    object surface_from_xlib(cairo_surface_t *surface)


def xlib_surface_create(xid: int):
    """Return a cairo.XlibSurface for the X11 window *xid*."""
    cdef Display *dpy = get_display()
    cdef XWindowAttributes attrs
    if not XGetWindowAttributes(dpy, <Window> xid, &attrs):
        raise RuntimeError(f"XGetWindowAttributes failed for {xid:#x}")
    cdef cairo_surface_t *surface = cairo_xlib_surface_create(dpy, <Window> xid, attrs.visual, attrs.width, attrs.height)
    if surface == NULL:
        raise RuntimeError(f"cairo_xlib_surface_create failed for {xid:#x}")
    return surface_from_xlib(surface)
