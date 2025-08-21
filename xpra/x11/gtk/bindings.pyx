# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic

from xpra.os_util import gi_import
from xpra.util.str_fn import strtobytes, csv

from xpra.log import Logger
log = Logger("x11", "bindings", "gtk")

GObject = gi_import("GObject")
GdkX11 = gi_import("GdkX11")
Gdk = gi_import("Gdk")
Gtk = gi_import("Gtk")


from xpra.x11.bindings.xlib cimport Display, Window, Visual, XEvent, XFree
from xpra.x11.bindings.events cimport parse_xevent, init_x11_events
from xpra.x11.bindings.events import get_x_event_signals, get_x_event_type_name
from xpra.x11.dispatch import route_event

from libc.stdint cimport uintptr_t
from xpra.gtk.bindings.gobject cimport wrap, unwrap


from xpra.x11.common import REPR_FUNCTIONS
def get_window_xid(window) -> str:
    return hex(window.get_xid())
REPR_FUNCTIONS[GdkX11.X11Window] = get_window_xid
def get_display_name(display) -> str:
    return display.get_name()
REPR_FUNCTIONS[Gdk.Display] = get_display_name


cdef extern from "gdk_x11_macros.h":
    int is_x11_display(void *)


cdef GdkDisplay * get_raw_display(display) except? NULL:
    return <GdkDisplay*> unwrap(display, Gdk.Display)


def is_X11_Display(display=None) -> bool:
    cdef GdkDisplay *gdk_display
    if display is None:
        manager = Gdk.DisplayManager.get()
        display = manager.get_default_display()
    if display is None:
        log("no default display!")
        return False
    try:
        gdk_display = get_raw_display(display)
    except TypeError:
        return False
    return bool(is_x11_display(gdk_display))

###################################
# Headers, python magic
###################################
cdef extern from "gtk-3.0/gdk/gdk.h":
    ctypedef struct GdkWindow:
        pass
    void gdk_display_flush(GdkDisplay *display)
    void gdk_x11_display_error_trap_push(GdkDisplay *display)
    int gdk_x11_display_error_trap_pop(GdkDisplay *display)

cdef extern from "gtk-3.0/gdk/gdkx.h":
    pass

cdef extern from "gtk-3.0/gdk/gdkproperty.h":
    ctypedef int gint
    ctypedef gint gboolean

cdef extern from "glib-2.0/glib-object.h":
    ctypedef struct cGObject "GObject":
        pass

cdef extern from "pygobject-3.0/pygobject.h":
    cGObject *pygobject_get(object box)
    object pygobject_new(cGObject * contents)

    ctypedef void* gpointer  # @UndefinedVariable
    ctypedef int GType
    ctypedef struct PyGBoxed:
        #PyObject_HEAD
        gpointer boxed
        GType gtype

######
# GDK primitives, and wrappers for Xlib
######

# gdk_region_get_rectangles (pygtk bug #517099)
cdef extern from "gtk-3.0/gdk/gdktypes.h":
    ctypedef struct cGdkVisual "GdkVisual":
        pass
    Visual * GDK_VISUAL_XVISUAL(cGdkVisual   *visual)

    Window GDK_WINDOW_XID(GdkWindow *)

    ctypedef struct GdkDisplay:
        pass
    Display * GDK_DISPLAY_XDISPLAY(GdkDisplay *)

    GdkDisplay * gdk_x11_lookup_xdisplay(Display *)


# Basic utilities:

def get_pywindow(Window xwindow) -> GdkX11.X11Window | None:
    if xwindow==0:
        return None
    display = Gdk.get_default_root_window().get_display()
    try:
        return GdkX11.X11Window.foreign_new_for_display(display, xwindow)
    except TypeError as e:
        log("cannot get gdk window for %s : %#x, %s", display, xwindow, e)
    return None


cdef Display * get_xdisplay() except? NULL:
    gdk_display = Gdk.get_default_root_window().get_display()
    return GDK_DISPLAY_XDISPLAY(get_raw_display(gdk_display))


###################################
# Event handling
###################################

# We need custom event handling in a few ways:
#   -- We need to listen to various events on client windows, even though they
#      have no GtkWidget associated.
#   -- We need to listen to various events that are not otherwise wrapped by
#      GDK at all.  (In particular, the SubstructureRedirect events.)
# To do this, we use two different hooks in GDK:
#   gdk_window_add_filter: This allows us to snoop on all events before they
#     are converted into GDK events.
# Our hooks in any case use the "xpra-route-events-to" GObject user data
# field of the gdk.Window's involved.  For the SubstructureRedirect
# events, we use this field of either the window that is making the request,
# or, if its field is unset, to the window that actually has
# SubstructureRedirect selected on it; for other events, we send it to the
# event window directly.
#
# So basically, to use this code:
#   -- Import this module to install the global event filters
#   -- Call win.set_data("xpra-route-events-to", obj) on random windows.
#   -- Call addXSelectInput or its convenience wrappers, substructureRedirect
#      and selectFocusChange.
#   -- Receive interesting signals on 'obj'.


cdef extern from "gtk-3.0/gdk/gdkevents.h":
    ctypedef enum GdkFilterReturn:
        GDK_FILTER_CONTINUE   # If we ignore the event
        GDK_FILTER_TRANSLATE  # If we converted the event to a GdkEvent
        GDK_FILTER_REMOVE     # If we handled the event and GDK should ignore it

    ctypedef struct GdkXEvent:
        pass
    ctypedef struct GdkEvent:
        pass

    ctypedef GdkFilterReturn (*GdkFilterFunc)(GdkXEvent *, GdkEvent *, void *) except GDK_FILTER_CONTINUE
    void gdk_window_add_filter(GdkWindow * w, GdkFilterFunc function, void * userdata)

    void gdk_window_remove_filter(GdkWindow *window, GdkFilterFunc function, void * data)


# No need to select for ClientMessage; in fact, one cannot select for
# ClientMessages.  If they are sent with an empty mask, then they go to the
# client that owns the window they are sent to, otherwise they go to any
# clients that are selecting for that mask they are sent with.



cdef GdkFilterReturn x_event_filter(GdkXEvent * e_gdk,
                                    GdkEvent * gdk_event,
                                    void * userdata) except GDK_FILTER_CONTINUE with gil:
    cdef object event_args
    cdef object pyev
    cdef double start = monotonic()
    cdef int etype

    cdef Display *display = get_xdisplay()
    cdef XEvent * e = <XEvent*>e_gdk
    try:
        pyev = parse_xevent(display, e)
    except Exception:
        log.error("Error parsing X11 event", exc_info=True)
        return GDK_FILTER_CONTINUE  # @UndefinedVariable
    log("parse_event(..)=%s", pyev)
    if not pyev:
        return GDK_FILTER_CONTINUE  # @UndefinedVariable
    try:
        etype = pyev.event_type
        event_args = get_x_event_signals(etype)
        #log("signals(%s)=%s", pyev, event_args)
        if event_args is not None:
            signal, parent_signal = event_args
            route_event(etype, pyev, signal, parent_signal)
        ename = get_x_event_type_name(etype) or etype
        log("x_event_filter event=%s/%s took %.1fms", event_args, ename, 1000.0*(monotonic()-start))
    except (KeyboardInterrupt, SystemExit):
        log("exiting on KeyboardInterrupt/SystemExit")
        Gtk.main_quit()
    except:
        log.warn("Unhandled exception in x_event_filter:", exc_info=True)
    return GDK_FILTER_CONTINUE  # @UndefinedVariable


cdef int _INIT_X11_FILTER_DONE = 0


def init_x11_filter() -> bool:
    log("init_x11_filter()")
    """ returns True if we did initialize it, False if it was already initialized """
    global _INIT_X11_FILTER_DONE
    cdef Display *display
    if _INIT_X11_FILTER_DONE==0:
        display = get_xdisplay()
        init_x11_events()
        gdk_window_add_filter(<GdkWindow*>0, x_event_filter, NULL)
        _INIT_X11_FILTER_DONE += 1
    return _INIT_X11_FILTER_DONE==1

def cleanup_x11_filter() -> bool:
    log("cleanup_x11_filter()")
    global _INIT_X11_FILTER_DONE
    _INIT_X11_FILTER_DONE -= 1
    if _INIT_X11_FILTER_DONE==0:
        gdk_window_remove_filter(<GdkWindow*>0, x_event_filter, NULL)
    return _INIT_X11_FILTER_DONE==0
