# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# This class simply hooks the current GDK display into
# the core X11 bindings.

from xpra.util.system import is_X11
from xpra.os_util import gi_import
from xpra.scripts.config import InitException
from xpra.x11.bindings.xlib cimport Display
from xpra.x11.bindings.display_source cimport set_display   # pylint: disable=syntax-error
from xpra.x11.bindings.display_source import set_display_name  # @UnresolvedImport


###################################
# Headers, python magic
###################################
cdef extern from "gtk-3.0/gdk/gdk.h":
    pass

cdef extern from "gtk-3.0/gdk/gdktypes.h":
    ctypedef struct GdkDisplay:
        pass

cdef extern from "gtk-3.0/gdk/gdkdisplay.h":
    GdkDisplay *gdk_display_get_default()

cdef extern from "gtk-3.0/gdk/gdkx.h":
    Display *gdk_x11_display_get_xdisplay(GdkDisplay *display)
    const char *gdk_display_get_name(GdkDisplay *display)


#this import magic will make the window.get_xid() available!
GdkX11 = gi_import("GdkX11")
if GdkX11 is None:
    raise RuntimeError("could not load GdkX11 3.0")

display = None
def init_gdk_display_source() -> None:
    global display
    import os
    backend = os.environ.get("GDK_BACKEND", "")
    if backend!="x11" and not is_X11():
        raise InitException("cannot use X11 bindings with %s and GTK3 (buggy)" % (backend or "non-X11",))
    if display:
        return
    Gdk = gi_import("Gdk")
    cdef GdkDisplay* gdk_display = gdk_display_get_default()
    if not gdk_display:
        raise InitException("cannot access display '%s'" % os.environ.get("DISPLAY", ""))
    #this next line actually ensures Gdk is initialized, somehow
    root = Gdk.get_default_root_window()
    if root is None:
        raise RuntimeError("could not get the default root window")
    display = Gdk.Display.get_default()
    #now we can get a display:
    cdef Display *x11_display = gdk_x11_display_get_xdisplay(gdk_display)
    set_display(x11_display)
    name = gdk_display_get_name(gdk_display).decode()
    set_display_name(name)

def close_gdk_display_source() -> None:
    #this triggers the garbage collection of the Display object:
    global display
    display = None
