# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


# This class simply hooks the current GDK display into
# the core X11 bindings.

from xpra.x11.bindings.display_source cimport set_display
from xpra.x11.bindings.display_source import set_display_name

import gobject
import gtk.gdk

###################################
# Headers, python magic
###################################
cdef extern from "X11/Xutil.h":
    pass

cdef extern from "gdk/gdk.h":
    pass
cdef extern from "gdk/gdkx.h":
    pass

# Serious black magic happens here (I owe these guys beers):
cdef extern from "pygobject.h":
    void pygobject_init(int req_major, int req_minor, int req_micro)
pygobject_init(-1, -1, -1)

cdef extern from "pygtk/pygtk.h":
    void init_pygtk()
init_pygtk()
# Now all the macros in those header files will work.

###################################
# GObject
###################################
cdef extern from "glib-2.0/glib-object.h":
    ctypedef struct cGObject "GObject":
        pass

cdef extern from "pygtk-2.0/pygobject.h":
    cGObject * pygobject_get(object box)

cdef cGObject * unwrap(box, pyclass) except? NULL:
    # Extract a raw GObject* from a PyGObject wrapper.
    assert issubclass(pyclass, gobject.GObject)
    if not isinstance(box, pyclass):
        raise TypeError("object %r is not a %r" % (box, pyclass))
    return pygobject_get(box)

cdef extern from "X11/Xlib.h":
    ctypedef struct Display:
        pass

cdef extern from "gtk-2.0/gdk/gdktypes.h":
    ctypedef struct cGdkDisplay "GdkDisplay":
        pass
    Display * GDK_DISPLAY_XDISPLAY(cGdkDisplay *)

#keep a reference to the gdk display
#since we use its "Display*"
display = None

######
# Get the real X11 display from a GDK display:
######
def init_gdk_display_source():
    global display
    cdef cGdkDisplay* gdk_display
    cdef Display * x11_display
    if not gtk.gdk.display_get_default():
        import os
        from xpra.scripts.config import InitException
        raise InitException("cannot access the default display '%s'" % os.environ.get("DISPLAY", ""))
    root_window = gtk.gdk.get_default_root_window()
    assert root_window, "cannot get the root window"
    display = root_window.get_display()
    assert root_window, "no display for root window %s" % root_window.xid
    gdk_display = <cGdkDisplay*> unwrap(display, gtk.gdk.Display)
    x11_display = GDK_DISPLAY_XDISPLAY(gdk_display)
    set_display(x11_display)
    set_display_name(display.get_name())

