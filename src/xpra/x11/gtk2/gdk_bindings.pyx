# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from __future__ import absolute_import

import os
import traceback

import gobject
from gtk import gdk

from xpra.gtk_common.quit import gtk_main_quit_really
from xpra.gtk_common.error import trap, XError
from xpra.x11.common import X11Event
from xpra.monotonic_time cimport monotonic_time
from xpra.util import csv

from xpra.log import Logger
log = Logger("x11", "bindings", "gtk")
verbose = Logger("x11", "bindings", "gtk", "verbose")


from libc.stdint cimport uintptr_t
from xpra.gtk_common.gtk2.gdk_bindings cimport wrap, unwrap, get_raw_display_for
from xpra.gtk_common.gtk2.gdk_bindings import get_display_for


from xpra.x11.common import REPR_FUNCTIONS
def get_window_xid(window):
    return "%#x" % window.xid
REPR_FUNCTIONS[gdk.Window] = get_window_xid
def get_display_name(display):
    return display.get_name()
REPR_FUNCTIONS[gdk.Display] = get_display_name


###################################
# Headers, python magic
###################################
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


###################################
# Raw Xlib and GDK
###################################

######
# Xlib primitives and constants
######

include "constants.pxi"
ctypedef unsigned long CARD32
ctypedef unsigned short CARD16
ctypedef unsigned char CARD8

cdef extern from "X11/X.h":
    unsigned long NoSymbol

cdef extern from "X11/Xlib.h":
    ctypedef struct Display:
        pass
    # To make it easier to translate stuff in the X header files into
    # appropriate pyrex declarations, without having to untangle the typedefs
    # over and over again, here are some convenience typedefs.  (Yes, CARD32
    # really is 64 bits on 64-bit systems.  Why? Because CARD32 was defined
    # as a long.. and a long is now 64-bit, it was easier to do this than
    # to change a lot of existing X11 client code)
    ctypedef CARD32 XID

    ctypedef int Bool
    ctypedef int Status
    ctypedef CARD32 Atom
    ctypedef XID Drawable
    ctypedef XID Window
    ctypedef XID Pixmap
    ctypedef CARD32 Time

    ctypedef CARD32 VisualID
    ctypedef CARD32 Colormap

    ctypedef struct Visual:
        void    *ext_data       #XExtData *ext_data;     /* hook for extension to hang data */
        VisualID visualid
        int c_class
        unsigned long red_mask
        unsigned long green_mask
        unsigned long blue_mask
        int bits_per_rgb
        int map_entries

    ctypedef struct XRectangle:
        short x, y
        unsigned short width, height


    int XFree(void * data)

    void XGetErrorText(Display * display, int code, char * buffer_return, int length)

    # There are way more event types than this; add them as needed.
    ctypedef struct XAnyEvent:
        int type
        unsigned long serial
        Bool send_event
        Display * display
        Window window
    # Needed to broadcast that we are a window manager, among other things:
    union payload_for_XClientMessageEvent:
        char b[20]
        short s[10]
        unsigned long l[5]
    ctypedef struct XClientMessageEvent:
        Atom message_type
        int format
        payload_for_XClientMessageEvent data
    # SubstructureRedirect-related events:
    ctypedef struct XMapRequestEvent:
        Window parent  # Same as xany.window, confusingly.
        Window window
    ctypedef struct XConfigureRequestEvent:
        Window parent  # Same as xany.window, confusingly.
        Window window
        int x, y, width, height, border_width
        Window above
        int detail
        unsigned long value_mask
    ctypedef struct XResizeRequestEvent:
        Window window
        int width, height
    ctypedef struct XReparentEvent:
        Window window
        Window parent
        int x, y
    ctypedef struct XCirculateRequestEvent:
        Window parent  # Same as xany.window, confusingly.
        Window window
        int place
    # For pointer grabs:
    ctypedef struct XCrossingEvent:
        unsigned long serial
        Bool send_event
        Window window
        Window root
        Window subwindow
        int mode                # NotifyNormal, NotifyGrab, NotifyUngrab
        int detail              # NotifyAncestor, NotifyVirtual, NotifyInferior, NotifyNonlinear,NotifyNonlinearVirtual
        Bool focus
        unsigned int state
    # Focus handling
    ctypedef struct XFocusChangeEvent:
        Window window
        int mode                #NotifyNormal, NotifyGrab, NotifyUngrab
        int detail              #NotifyAncestor, NotifyVirtual, NotifyInferior,
                                #NotifyNonlinear,NotifyNonlinearVirtual, NotifyPointer,
                                #NotifyPointerRoot, NotifyDetailNone
    ctypedef struct XMotionEvent:
        Window window           #event window reported relative to
        Window root             #root window that the event occurred on
        Window subwindow        #child window
        Time time               #milliseconds
        int x, y                #pointer x, y coordinates in event window
        int x_root, y_root      #coordinates relative to root
        unsigned int state      #key or button mask
        char is_hint            #detail
        Bool same_screen        #same screen
    # We have to generate synthetic ConfigureNotify's:
    ctypedef struct XConfigureEvent:
        Window event    # Same as xany.window, confusingly.
                        # The selected-on window.
        Window window   # The effected window.
        int x, y, width, height, border_width
        Window above
        Bool override_redirect
    ctypedef struct XCreateWindowEvent:
        Window window
        int width
        int height
    # The only way we can learn about override redirects is through MapNotify,
    # which means we need to be able to get MapNotify for windows we have
    # never seen before, which means we can't rely on GDK:
    ctypedef struct XMapEvent:
        Window window
        Bool override_redirect
    ctypedef struct XUnmapEvent:
        Window window
    ctypedef struct XDestroyWindowEvent:
        Window window
    ctypedef struct XPropertyEvent:
        Atom atom
    ctypedef struct XKeyEvent:
        unsigned int keycode, state
    ctypedef struct XButtonEvent:
        Window root
        Window subwindow
        Time time
        int x, y                # pointer x, y coordinates in event window
        int x_root, y_root      # coordinates relative to root */
        unsigned int state      # key or button mask
        unsigned int button
        Bool same_screen
    ctypedef struct XGenericEventCookie:
        int            type     # of event. Always GenericEvent
        unsigned long  serial
        Bool           send_event
        Display        *display
        int            extension    #major opcode of extension that caused the event
        int            evtype       #actual event type
        unsigned int   cookie
        void           *data
    ctypedef union XEvent:
        int type
        XAnyEvent xany
        XKeyEvent xkey
        XButtonEvent xbutton
        XMapRequestEvent xmaprequest
        XConfigureRequestEvent xconfigurerequest
        XResizeRequestEvent xresizerequest
        XCirculateRequestEvent xcirculaterequest
        XConfigureEvent xconfigure
        XCrossingEvent xcrossing
        XFocusChangeEvent xfocus
        XMotionEvent xmotion
        XClientMessageEvent xclient
        XMapEvent xmap
        XCreateWindowEvent xcreatewindow
        XUnmapEvent xunmap
        XReparentEvent xreparent
        XDestroyWindowEvent xdestroywindow
        XPropertyEvent xproperty
        XGenericEventCookie xcookie

    Bool XQueryExtension(Display * display, char *name,
                         int *major_opcode_return, int *first_event_return, int *first_error_return)

    Status XQueryTree(Display * display, Window w,
                      Window * root, Window * parent,
                      Window ** children, unsigned int * nchildren)


cdef extern from "X11/extensions/xfixeswire.h":
    unsigned int XFixesCursorNotify
    unsigned long XFixesDisplayCursorNotifyMask

cdef extern from "X11/extensions/shape.h":
    Bool XShapeQueryExtension(Display *display, int *event_base, int *error_base)
    ctypedef struct XShapeEvent:
        Window window
        int kind            #ShapeBounding or ShapeClip
        int x, y            #extents of new region
        unsigned width, height
        Bool shaped         #true if the region exists

cdef extern from "X11/extensions/Xdamage.h":
    ctypedef XID Damage
    unsigned int XDamageNotify
    ctypedef struct XDamageNotifyEvent:
        Damage damage
        int level
        Bool more
        XRectangle area
    Bool XDamageQueryExtension(Display *, int * event_base, int * error_base)

cdef extern from "X11/extensions/Xfixes.h":
    Bool XFixesQueryExtension(Display *, int *event_base, int *error_base)
    ctypedef struct XFixesCursorImage:
        short x
        short y
        unsigned short width
        unsigned short height
        unsigned short xhot
        unsigned short yhot
        unsigned long cursor_serial
        unsigned long* pixels
        Atom atom
        char* name
    ctypedef struct XFixesCursorNotifyEvent:
        int type
        unsigned long serial
        Bool send_event
        Display *display
        Window window
        int subtype
        unsigned long cursor_serial
        Time timestamp
        Atom cursor_name

cdef extern from "X11/extensions/XKB.h":
    unsigned int XkbUseCoreKbd
    unsigned int XkbBellNotifyMask
    unsigned int XkbBellNotify
    ctypedef struct XkbAnyEvent:
        unsigned long   serial
        Bool            send_event
        Display *       display
        Time            time
        int             xkb_type
        unsigned int    device

cdef extern from "X11/XKBlib.h":
    Bool XkbQueryExtension(Display *, int *opcodeReturn, int *eventBaseReturn, int *errorBaseReturn, int *majorRtrn, int *minorRtrn)

cdef extern from "X11/extensions/XKBproto.h":
    ctypedef struct XkbBellNotifyEvent:
        int         type
        CARD32      serial
        Bool        send_event
        Display*    display
        Time        time
        int         xkb_type
        int         device
        int         percent
        int         pitch
        int         duration
        int         bell_class
        int         bell_id
        Atom        name
        Window      window
        Bool        event_only


######
# GDK primitives, and wrappers for Xlib
######

# gdk_region_get_rectangles (pygtk bug #517099)
cdef extern from "gtk-2.0/gdk/gdktypes.h":
    ctypedef void* GdkAtom
    ctypedef struct cGdkVisual "GdkVisual":
        pass
    Visual * GDK_VISUAL_XVISUAL(cGdkVisual   *visual)

    ctypedef struct cGdkWindow "GdkWindow":
        pass
    Window GDK_WINDOW_XID(cGdkWindow *)

    ctypedef struct cGdkDisplay "GdkDisplay":
        pass
    Display * GDK_DISPLAY_XDISPLAY(cGdkDisplay *)

    cGdkDisplay * gdk_x11_lookup_xdisplay(Display *)

    GdkAtom GDK_NONE
    # FIXME: this should have stricter type checking
    object PyGdkAtom_New(GdkAtom)
    Atom gdk_x11_get_xatom_by_name(char *atom_name)
    GdkAtom gdk_x11_xatom_to_atom_for_display(cGdkDisplay *, Atom)


# Basic utilities:

cdef int get_xwindow(pywindow):
    return GDK_WINDOW_XID(<cGdkWindow*>unwrap(pywindow, gdk.Window))

def get_pywindow(display_source, xwindow):
    return _get_pywindow(display_source, xwindow)

cdef object _get_pywindow(object display_source, Window xwindow):
    if xwindow==0:
        return None
    disp = get_display_for(display_source)
    win = gdk.window_foreign_new_for_display(disp, xwindow)
    if win is None:
        verbose("cannot get gdk window for %s : %#x", display_source, xwindow)
        raise XError(BadWindow)
    return win

def get_xvisual(pyvisual):
    cdef Visual * xvisual
    xvisual = _get_xvisual(pyvisual)
    if xvisual==NULL:
        return  -1
    return xvisual.visualid

cdef Visual *_get_xvisual(pyvisual):
    return GDK_VISUAL_XVISUAL(<cGdkVisual*>unwrap(pyvisual, gdk.Visual))


cdef Display * get_xdisplay_for(obj) except? NULL:
    return GDK_DISPLAY_XDISPLAY(get_raw_display_for(obj))


def get_xatom(str_or_xatom):
    """Returns the X atom corresponding to the given Python string or Python
    integer (assumed to already be an X atom)."""
    if isinstance(str_or_xatom, int):
        i = int(str_or_xatom)
        assert i>=0, "invalid int atom value %s" % str_or_xatom
        return i
    if isinstance(str_or_xatom, long):
        l = long(str_or_xatom)
        assert l>=0, "invalid long atom value %s" % str_or_xatom
        return l
    assert isinstance(str_or_xatom, str), "argument is not a string or number: %s" % type(str_or_xatom)
    gdkatom = gdk.atom_intern(str_or_xatom)
    if not gdkatom:
        return  0
    return gdk_x11_get_xatom_by_name(str_or_xatom)

cdef GdkAtom get_gdkatom(display_source, xatom):
    if long(xatom) > long(2) ** 32:
        raise Exception("weirdly huge purported xatom: %s" % xatom)
    if xatom==0:
        return GDK_NONE
    cdef cGdkDisplay * disp
    cdef GdkAtom gdk_atom
    disp = get_raw_display_for(display_source)
    gdk_atom = gdk_x11_xatom_to_atom_for_display(disp, xatom)
    return gdk_atom

def get_pyatom(display_source, xatom):
    cdef GdkAtom gdk_atom = get_gdkatom(display_source, xatom)
    if gdk_atom==GDK_NONE:
        return ""
    return str(PyGdkAtom_New(gdk_atom))


# Children listing
cdef _query_tree(pywindow):
    cdef Window root = 0, parent = 0
    cdef Window * children = <Window *> 0
    cdef unsigned int nchildren = 0
    cdef object pychildren
    cdef object pyparent
    if not XQueryTree(get_xdisplay_for(pywindow),
                      get_xwindow(pywindow),
                      &root, &parent, &children, &nchildren):
        return (None, [])
    pychildren = []
    for i from 0 <= i < nchildren:
        #we cannot get the gdk window for wid=0
        if children[i]>0:
            pychildren.append(_get_pywindow(pywindow, children[i]))
    # Apparently XQueryTree sometimes returns garbage in the 'children'
    # pointer when 'nchildren' is 0, which then leads to a segfault when we
    # try to XFree the non-NULL garbage.
    if nchildren > 0 and children != NULL:
        XFree(children)
    if parent != XNone:
        pyparent = _get_pywindow(pywindow, parent)
    else:
        pyparent = None
    return (pyparent, pychildren)

def get_children(pywindow):
    (pyparent, pychildren) = _query_tree(pywindow)
    return pychildren

def get_parent(pywindow):
    (pyparent, pychildren) = _query_tree(pywindow)
    return pyparent


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
#     are converted into GDK events.  We use this to capture:
#       MapRequest
#       ConfigureRequest
#       FocusIn
#       FocusOut
#       ClientMessage
#     (We could get ClientMessage from PyGTK using the API below, but
#     PyGTK's ClientMessage handling is annoying -- see bug #466990.)
#   gdk_event_handler_set: This allows us to snoop on all events after they
#     have gone through the GDK event handling machinery, just before they
#     enter GTK.  Everything that we catch in this manner could just as well
#     be caught by the gdk_window_add_filter technique, but waiting until here
#     lets us write less binding gunk.  We use this to catch:
#       PropertyNotify
#       Unmap
#       Destroy
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

cdef extern from "gtk-2.0/gdk/gdkevents.h":
    ctypedef enum GdkFilterReturn:
        GDK_FILTER_CONTINUE   # If we ignore the event
        GDK_FILTER_TRANSLATE  # If we converted the event to a GdkEvent
        GDK_FILTER_REMOVE     # If we handled the event and GDK should ignore it

    ctypedef struct GdkXEvent:
        pass
    ctypedef struct GdkEvent:
        pass

    ctypedef GdkFilterReturn (*GdkFilterFunc)(GdkXEvent *, GdkEvent *, void *)
    void gdk_window_add_filter(cGdkWindow * w,
                               GdkFilterFunc filter,
                               void * userdata)

    void gdk_window_remove_filter(cGdkWindow *window,
                               GdkFilterFunc function,
                               void * data)


# No need to select for ClientMessage; in fact, one cannot select for
# ClientMessages.  If they are sent with an empty mask, then they go to the
# client that owns the window they are sent to, otherwise they go to any
# clients that are selecting for that mask they are sent with.

_ev_receiver_key = "xpra-route-events-to"
def add_event_receiver(window, receiver, max_receivers=3):
    receivers = window.get_data(_ev_receiver_key)
    if receivers is None:
        receivers = set()
        window.set_data(_ev_receiver_key, receivers)
    if max_receivers>0 and len(receivers)>max_receivers:
        log.warn("already too many receivers for window %s: %s, adding %s to %s", window, len(receivers), receiver, receivers)
        traceback.print_stack()
    if receiver not in receivers:
        receivers.add(receiver)

def remove_event_receiver(window, receiver):
    receivers = window.get_data(_ev_receiver_key)
    if receivers is None:
        return
    receivers.discard(receiver)
    if not receivers:
        window.set_data(_ev_receiver_key, None)

#only used for debugging:
def get_event_receivers(window):
    return window.get_data(_ev_receiver_key)

def cleanup_all_event_receivers():
    root = gdk.get_default_root_window()
    root.set_data(_ev_receiver_key, None)
    for window in get_children(root):
        receivers = window.get_data(_ev_receiver_key)
        if receivers is not None:
            window.set_data(_ev_receiver_key, None)


cdef int CursorNotify = -1
cdef int XKBNotify = -1
cdef int ShapeNotify = -1
x_event_signals = {}
x_event_type_names = {}
names_to_event_type = {}
#sometimes we may want to debug routing for certain X11 event types
debug_route_events = []

def get_error_text(code):
    if type(code)!=int:
        return code
    cdef Display * display                              #@DuplicatedSignature
    display = get_xdisplay_for(gdk.get_default_root_window())
    cdef char[128] buffer
    XGetErrorText(display, code, buffer, 128)
    return str(buffer[:128])

cdef int get_XKB_event_base():
    cdef int opcode = 0
    cdef int event_base = 0
    cdef int error_base = 0
    cdef int major = 0
    cdef int minor = 0
    cdef Display * xdisplay                             #@DuplicatedSignature
    display = gdk.get_default_root_window().get_display()
    xdisplay = get_xdisplay_for(display)
    if not XkbQueryExtension(xdisplay, &opcode, &event_base, &error_base, &major, &minor):
        log.warn("Warning: Xkb extension is not available")
        return -1
    verbose("get_XKB_event_base(%s)=%i", display.get_name(), event_base)
    return event_base

cdef int get_XFixes_event_base():
    cdef int event_base = 0                             #@DuplicatedSignature
    cdef int error_base = 0                             #@DuplicatedSignature
    cdef Display * xdisplay                             #@DuplicatedSignature
    display = gdk.get_default_root_window().get_display()
    xdisplay = get_xdisplay_for(display)
    if not XFixesQueryExtension(xdisplay, &event_base, &error_base):
        log.warn("Warning: XFixes extension is not available")
        return -1
    verbose("get_XFixes_event_base(%s)=%i", display.get_name(), event_base)
    assert event_base>0, "invalid event base for XFixes"
    return event_base

cdef int get_XDamage_event_base():
    cdef int event_base = 0                             #@DuplicatedSignature
    cdef int error_base = 0                             #@DuplicatedSignature
    cdef Display * xdisplay                             #@DuplicatedSignature
    display = gdk.get_default_root_window().get_display()
    xdisplay = get_xdisplay_for(display)
    if not XDamageQueryExtension(xdisplay, &event_base, &error_base):
        log.warn("Warning: XDamage extension is not available")
        return -1
    verbose("get_XDamage_event_base(%s)=%i", display.get_name(), event_base)
    assert event_base>0, "invalid event base for XDamage"
    return event_base

cdef int get_XShape_event_base():
    cdef Display * xdisplay                             #@DuplicatedSignature
    display = gdk.get_default_root_window().get_display()
    xdisplay = get_xdisplay_for(display)
    cdef int event_base = 0, ignored = 0
    if not XShapeQueryExtension(xdisplay, &event_base, &ignored):
        log.warn("Warning: XShape extension is not available")
        return -1
    return event_base


cdef init_x11_events():
    add_x_event_signals({
        MapRequest          : (None, "child-map-request-event"),
        ConfigureRequest    : (None, "child-configure-request-event"),
        FocusIn             : ("xpra-focus-in-event", None),
        FocusOut            : ("xpra-focus-out-event", None),
        ClientMessage       : ("xpra-client-message-event", None),
        CreateNotify        : ("xpra-create-event", None),
        MapNotify           : ("xpra-map-event", "xpra-child-map-event"),
        UnmapNotify         : ("xpra-unmap-event", "xpra-child-unmap-event"),
        DestroyNotify       : ("xpra-destroy-event", None),
        ConfigureNotify     : ("xpra-configure-event", None),
        ReparentNotify      : ("xpra-reparent-event", None),
        PropertyNotify      : ("xpra-property-notify-event", None),
        KeyPress            : ("xpra-key-press-event", None),
        EnterNotify         : ("xpra-enter-event", None),
        LeaveNotify         : ("xpra-leave-event", None),
        MotionNotify        : ("xpra-motion-event", None)       #currently unused, just defined for debugging purposes
        })
    add_x_event_type_names({
        KeyPress            : "KeyPress",
        KeyRelease          : "KeyRelease",
        ButtonPress         : "ButtonPress",
        ButtonRelease       : "ButtonRelease",
        MotionNotify        : "MotionNotify",
        EnterNotify         : "EnterNotify",
        LeaveNotify         : "LeaveNotify",
        FocusIn             : "FocusIn",
        FocusOut            : "FocusOut",
        KeymapNotify        : "KeymapNotify",
        Expose              : "Expose",
        GraphicsExpose      : "GraphicsExpose",
        NoExpose            : "NoExpose",
        VisibilityNotify    : "VisibilityNotify",
        CreateNotify        : "CreateNotify",
        DestroyNotify       : "DestroyNotify",
        UnmapNotify         : "UnmapNotify",
        MapNotify           : "MapNotify",
        MapRequest          : "MapRequest",
        ReparentNotify      : "ReparentNotify",
        ConfigureNotify     : "ConfigureNotify",
        ConfigureRequest    : "ConfigureRequest",
        GravityNotify       : "GravityNotify",
        ResizeRequest       : "ResizeRequest",
        CirculateNotify     : "CirculateNotify",
        CirculateRequest    : "CirculateRequest",
        PropertyNotify      : "PropertyNotify",
        SelectionClear      : "SelectionClear",
        SelectionRequest    : "SelectionRequest",
        SelectionNotify     : "SelectionNotify",
        ColormapNotify      : "ColormapNotify",
        ClientMessage       : "ClientMessage",
        MappingNotify       : "MappingNotify",
        GenericEvent        : "GenericEvent",
        })
    cdef int event_base = get_XShape_event_base()
    if event_base>=0:
        global ShapeNotify
        ShapeNotify = event_base
        add_x_event_signal(ShapeNotify, ("xpra-shape-event", None))
        add_x_event_type_name(ShapeNotify, "ShapeNotify")
        log("added ShapeNotify=%s", ShapeNotify)
    event_base = get_XKB_event_base()
    if event_base>=0:
        global XKBNotify
        XKBNotify = event_base
        add_x_event_signal(XKBNotify, ("xpra-xkb-event", None))
        add_x_event_type_name(XKBNotify, "XKBNotify")
    event_base = get_XFixes_event_base()
    if event_base>=0:
        global CursorNotify
        CursorNotify = XFixesCursorNotify+event_base
        add_x_event_signal(CursorNotify, ("xpra-cursor-event", None))
        add_x_event_type_name(CursorNotify, "CursorNotify")
    event_base = get_XDamage_event_base()
    if event_base>0:
        global DamageNotify
        DamageNotify = XDamageNotify+event_base
        add_x_event_signal(DamageNotify, ("xpra-damage-event", None))
        add_x_event_type_name(DamageNotify, "DamageNotify")


def add_x_event_signal(event, mapping):
    global x_event_signals
    x_event_signals[event] = mapping

def add_x_event_signals(event_signals):
    global x_event_signals
    x_event_signals.update(event_signals)

def add_x_event_type_name(event, name):
    global x_event_type_names
    x_event_type_names[event] = name
    names_to_event_type[name] = event
    set_debug_events()

def add_x_event_type_names(event_type_names):
    global x_event_type_names, names_to_event_type
    x_event_type_names.update(event_type_names)
    for k,v in event_type_names.items():
        names_to_event_type[v] = k
    set_debug_events()
    verbose("x_event_signals=%s", x_event_signals)
    verbose("event_type_names=%s", x_event_type_names)
    verbose("names_to_event_type=%s", names_to_event_type)

def set_debug_events():
    global debug_route_events
    XPRA_X11_DEBUG_EVENTS = os.environ.get("XPRA_X11_DEBUG_EVENTS", "")
    debug_set = set()
    ignore_set = set()
    for n in XPRA_X11_DEBUG_EVENTS.split(","):
        name = n.strip()
        if len(name)==0:
            continue
        if name[0]=="-":
            event_set = ignore_set
            name = name[1:]
        else:
            event_set = debug_set
        if name=="*":
            events = names_to_event_type.keys()
        elif name in names_to_event_type:
            events = [name]
        else:
            log("unknown X11 debug event type: %s", name)
            continue
        #add to correct set:
        for e in events:
            event_set.add(e)
    events = debug_set.difference(ignore_set)
    debug_route_events = [names_to_event_type.get(x) for x in events]
    if len(events)>0:
        log.warn("debugging of X11 events enabled for:")
        log.warn(" %s", csv(events))
        log.warn(" event codes: %s", csv(debug_route_events))


x_event_parsers = {}
def add_x_event_parser(extension_opcode, parser):
    global x_event_parsers
    x_event_parsers[extension_opcode] = parser


#and change this debugging on the fly, programmatically:
def add_debug_route_event(event_type):
    global debug_route_events
    debug_route_events.append(event_type)
def remove_debug_route_event(event_type):
    global debug_route_events
    debug_route_events.remove(event_type)


catchall_receivers = {}
def add_catchall_receiver(signal, handler):
    global catchall_receivers
    catchall_receivers.setdefault(signal, []).append(handler)
    log("add_catchall_receiver(%s, %s) -> %s", signal, handler, catchall_receivers)

def remove_catchall_receiver(signal, handler):
    global catchall_receivers
    try:
        receivers = catchall_receivers.get(signal).remove(handler)
    except:
        pass
    log("remove_catchall_receiver(%s, %s) -> %s", signal, handler, catchall_receivers)


fallback_receivers = {}
def add_fallback_receiver(signal, handler):
    global fallback_receivers
    fallback_receivers.setdefault(signal, []).append(handler)
    log("add_fallback_receiver(%s, %s) -> %s", signal, handler, fallback_receivers)

def remove_fallback_receiver(signal, handler):
    global fallback_receivers
    try:
        receivers = fallback_receivers.get(signal).remove(handler)
    except:
        pass
    log("remove_fallback_receiver(%s, %s) -> %s", signal, handler, fallback_receivers)


cdef _maybe_send_event(unsigned int DEBUG, handlers, signal, event, hinfo="window"):
    if not handlers:
        if DEBUG:
            log.info("  no handler registered for %s (%s), ignoring event", hinfo, handlers)
        return
    # Copy the 'handlers' list, because signal handlers might cause items
    # to be added or removed from it while we are iterating:
    for handler in tuple(handlers):
        signals = gobject.signal_list_names(handler)
        if signal in signals:
            if DEBUG:
                log.info("  forwarding event to a %s %s handler's %s signal", type(handler).__name__, hinfo, signal)
            handler.emit(signal, event)
            if DEBUG:
                log.info("  forwarded")
        elif DEBUG:
            log.info("  not forwarding to %s handler, it has no %s signal (it has: %s)",
                type(handler).__name__, signal, signals)

cdef _route_event(int etype, event, signal, parent_signal):
    # Sometimes we get GDK events with event.window == None, because they are
    # for windows we have never created a GdkWindow object for, and GDK
    # doesn't do so just for this event.  As far as I can tell this only
    # matters for override redirect windows when they disappear, and we don't
    # care about those anyway.
    global debug_route_events, x_event_type_names
    cdef unsigned int DEBUG = etype in debug_route_events
    if DEBUG:
        log.info("%s event %#x : %s", x_event_type_names.get(etype, etype), event.serial, event)
    handlers = None
    if event.window is None:
        if DEBUG:
            log.info("  event.window is None, ignoring")
        assert etype in (UnmapNotify, DestroyNotify), \
                "event window is None for event type %s!" % (x_event_type_names.get(etype, etype))
    elif event.window is event.delivered_to:
        if signal is not None:
            window = event.window
            if DEBUG:
                log.info("  delivering event to window itself: %#x  (signal=%s)", window.xid, signal)
            handlers = window.get_data(_ev_receiver_key)
            _maybe_send_event(DEBUG, handlers, signal, event, "window %#x" % window.xid)
        elif DEBUG:
            log.info("  received event on window itself but have no signal for that")
    else:
        if parent_signal is not None:
            window = event.delivered_to
            if DEBUG:
                log.info("  delivering event to parent window: %#x (signal=%s)", window.xid, parent_signal)
            handlers = window.get_data(_ev_receiver_key)
            _maybe_send_event(DEBUG, handlers, parent_signal, event, "parent window %#x" % window.xid)
        else:
            if DEBUG:
                log.info("  received event on a parent window but have no parent signal")
    #fallback only fires if nothing else has fired yet:
    if not handlers:
        global fallback_receivers
        handlers = fallback_receivers.get(signal)
        _maybe_send_event(DEBUG, handlers, signal, event, "fallback")
    #always fire those:
    global catchall_receivers
    handlers = catchall_receivers.get(signal)
    _maybe_send_event(DEBUG, handlers, signal, event, "catchall")


cdef object _gw(display, Window xwin):
    if xwin==0:
        return None
    gdk.error_trap_push()
    try:
        disp = get_display_for(display)
        win = gdk.window_foreign_new_for_display(disp, xwin)
        gdk.flush()
        error = gdk.error_trap_pop()
    except Exception as e:
        verbose("cannot get gdk window for %s, %s: %s", display, xwin, e)
        error = gdk.error_trap_pop()
        if error:
            verbose("ignoring XError %s in unwind", get_error_text(error))
        raise XError(e)
    if error:
        verbose("cannot get gdk window for %s, %s: %s", display, xwin, get_error_text(error))
        raise XError(error)
    if win is None:
        verbose("cannot get gdk window for %s, %s", display, xwin)
        raise XError(BadWindow)
    return win


cdef GdkFilterReturn x_event_filter(GdkXEvent * e_gdk,
                                    GdkEvent * gdk_event,
                                    void * userdata) with gil:
    cdef object event_args
    cdef object pyev
    cdef double start = monotonic_time()
    cdef XEvent *e = <XEvent*>e_gdk
    cdef int etype

    try:
        pyev = parse_xevent(e_gdk)
    except Exception as exc:
        log.error("Error parsing X11 event: %s", exc, exc_info=True)
        return GDK_FILTER_CONTINUE
    log("parse_event(..)=%s", pyev)
    if not pyev:
        return GDK_FILTER_CONTINUE
    try:
        global x_event_signals, x_event_type_names
        etype = pyev.type
        event_args = x_event_signals.get(etype)
        #log("signals(%s)=%s", pyev, event_args)
        if event_args is not None:
            signal, parent_signal = event_args
            _route_event(etype, pyev, signal, parent_signal)
        log("x_event_filter event=%s/%s took %.1fms", event_args, x_event_type_names.get(etype, etype), 1000.0*(monotonic_time()-start))
    except (KeyboardInterrupt, SystemExit):
        verbose("exiting on KeyboardInterrupt/SystemExit")
        gtk_main_quit_really()
    except:
        log.warn("Unhandled exception in x_event_filter:", exc_info=True)
    return GDK_FILTER_CONTINUE


cdef parse_xevent(GdkXEvent * e_gdk) with gil:
    cdef XEvent * e = <XEvent*>e_gdk
    cdef XDamageNotifyEvent * damage_e
    cdef XFixesCursorNotifyEvent * cursor_e
    cdef XkbAnyEvent * xkb_e
    cdef XkbBellNotifyEvent * bell_e
    cdef XShapeEvent * shape_e
    cdef object event_args
    cdef object d
    cdef object pyev
    cdef int etype = e.type

    global x_event_type_names, x_event_signals
    event_type = x_event_type_names.get(etype, etype)
    if e.xany.send_event and etype not in (ClientMessage, UnmapNotify):
        log("x_event_filter ignoring %s send_event", event_type)
        return None

    d = wrap(<cGObject*>gdk_x11_lookup_xdisplay(e.xany.display))

    if etype == GenericEvent:
        global x_event_parsers
        parser = x_event_parsers.get(e.xcookie.extension)
        if parser:
            #log("calling %s%s", parser, (d, <uintptr_t> &e.xcookie))
            return parser(d, <uintptr_t> &e.xcookie)
        return None

    event_args = x_event_signals.get(etype)
    log("x_event_filter event=%s/%s window=%#x", event_args, event_type, e.xany.window)
    if event_args is None:
        return None

    pyev = X11Event(event_type)
    pyev.type = etype
    pyev.display = d
    pyev.send_event = e.xany.send_event
    pyev.serial = e.xany.serial
    # Unmarshal:
    try:
        if etype != XKBNotify:
            pyev.delivered_to = _gw(d, e.xany.window)

        if etype == DamageNotify:
            damage_e = <XDamageNotifyEvent*>e
            pyev.window = _gw(d, e.xany.window)
            pyev.damage = damage_e.damage
            pyev.x = damage_e.area.x
            pyev.y = damage_e.area.y
            pyev.width = damage_e.area.width
            pyev.height = damage_e.area.height
        elif etype == MapRequest:
            pyev.window = _gw(d, e.xmaprequest.window)
        elif etype == ConfigureRequest:
            pyev.window = _gw(d, e.xconfigurerequest.window)
            pyev.x = e.xconfigurerequest.x
            pyev.y = e.xconfigurerequest.y
            pyev.width = e.xconfigurerequest.width
            pyev.height = e.xconfigurerequest.height
            pyev.border_width = e.xconfigurerequest.border_width
            try:
                # In principle there are two cases here: .above is
                # XNone (i.e. not specified in the original request),
                # or .above is an invalid window (i.e. it was
                # specified by the client, but it specified something
                # weird).  I don't see any reason to handle these
                # differently, though.
                pyev.above = _gw(d, e.xconfigurerequest.above)
            except XError:
                pyev.above = None
            pyev.above = e.xconfigurerequest.above
            pyev.detail = e.xconfigurerequest.detail
            pyev.value_mask = e.xconfigurerequest.value_mask
        elif etype == ResizeRequest:
            pyev.window = _gw(d, e.xresizerequest.window)
            pyev.width = e.xresizerequest.width
            pyev.height = e.xresizerequest.height
        elif etype in (FocusIn, FocusOut):
            pyev.window = _gw(d, e.xfocus.window)
            pyev.mode = e.xfocus.mode
            pyev.detail = e.xfocus.detail
        elif etype in (EnterNotify, LeaveNotify):
            pyev.window = _gw(d, e.xcrossing.window)
            pyev.mode = e.xcrossing.mode
            pyev.detail = e.xcrossing.detail
            pyev.subwindow = _gw(d, e.xcrossing.subwindow)
            pyev.focus = e.xcrossing.focus
        elif etype == ClientMessage:
            pyev.window = _gw(d, e.xany.window)
            if long(e.xclient.message_type) > (long(2) ** 32):
                log.warn("Xlib claims that this ClientEvent's 32-bit "
                         + "message_type is %s.  "
                         + "Note that this is >2^32.  "
                         + "This makes no sense, so I'm ignoring it.",
                         e.xclient.message_type)
                return GDK_FILTER_CONTINUE
            pyev.message_type = get_pyatom(d, e.xclient.message_type)
            pyev.format = e.xclient.format
            # I am lazy.  Add this later if needed for some reason.
            if pyev.format != 32:
                #things like _KDE_SPLASH_PROGRESS and _NET_STARTUP_INFO will come through here
                log("FIXME: Ignoring ClientMessage type=%s with format=%s (!=32)", pyev.message_type, pyev.format)
                return GDK_FILTER_CONTINUE
            pieces = []
            for i in range(5):
                # Mask with 0xffffffff to prevent sign-extension on
                # architectures where Python's int is 64-bits.
                pieces.append(int(e.xclient.data.l[i]) & 0xffffffff)
            pyev.data = tuple(pieces)
        elif etype == CreateNotify:
            pyev.window = _gw(d, e.xcreatewindow.window)
            pyev.width = e.xcreatewindow.width
            pyev.height = e.xcreatewindow.height
        elif etype == MapNotify:
            pyev.window = _gw(d, e.xmap.window)
            pyev.override_redirect = e.xmap.override_redirect
        elif etype == UnmapNotify:
            pyev.window = _gw(d, e.xunmap.window)
        elif etype == DestroyNotify:
            pyev.window = _gw(d, e.xdestroywindow.window)
        elif etype == PropertyNotify:
            pyev.window = _gw(d, e.xany.window)
            pyev.atom = trap.call_synced(get_pyatom, d, e.xproperty.atom)
        elif etype == ConfigureNotify:
            pyev.window = _gw(d, e.xconfigure.window)
            pyev.x = e.xconfigure.x
            pyev.y = e.xconfigure.y
            pyev.width = e.xconfigure.width
            pyev.height = e.xconfigure.height
            pyev.border_width = e.xconfigure.border_width
            pyev.above = e.xconfigure.above
        elif etype == CirculateNotify:
            pyev.window = _gw(d, e.xcirculaterequest.window)
            pyev.place = e.xcirculaterequest.place
        elif etype == ReparentNotify:
            pyev.window = _gw(d, e.xreparent.window)
        elif etype == KeyPress:
            pyev.window = _gw(d, e.xany.window)
            pyev.hardware_keycode = e.xkey.keycode
            pyev.state = e.xkey.state
        elif etype == CursorNotify:
            pyev.window = _gw(d, e.xany.window)
            cursor_e = <XFixesCursorNotifyEvent*>e
            pyev.cursor_serial = cursor_e.cursor_serial
            pyev.cursor_name = trap.call_synced(get_pyatom, d, cursor_e.cursor_name)
        elif etype == MotionNotify:
            pyev.window = _gw(d, e.xmotion.window)
            pyev.root = _gw(d, e.xmotion.root)
            pyev.subwindow = _gw(d, e.xmotion.subwindow)
            pyev.time = e.xmotion.time
            pyev.x = e.xmotion.x
            pyev.y = e.xmotion.y
            pyev.x_root = e.xmotion.x_root
            pyev.y_root = e.xmotion.y_root
            pyev.state = e.xmotion.state
            pyev.is_hint = e.xmotion.is_hint
            pyev.same_screen = e.xmotion.same_screen
        elif etype == ShapeNotify:
            shape_e = <XShapeEvent*> e
            pyev.window = _gw(d, shape_e.window)
            pyev.kind = shape_e.kind
            pyev.x = shape_e.x
            pyev.y = shape_e.y
            pyev.width = shape_e.width
            pyev.height = shape_e.height
            pyev.shaped = shape_e.shaped
        elif etype == XKBNotify:
            # note we could just cast directly to XkbBellNotifyEvent
            # but this would be dirty, and we may want to catch
            # other types of XKB events in the future
            xkb_e = <XkbAnyEvent*>e
            verbose("XKBNotify event received xkb_type=%s", xkb_e.xkb_type)
            if xkb_e.xkb_type!=XkbBellNotify:
                return GDK_FILTER_CONTINUE
            bell_e = <XkbBellNotifyEvent*>e
            pyev.subtype = "bell"
            pyev.device = int(bell_e.device)
            pyev.percent = int(bell_e.percent)
            pyev.pitch = int(bell_e.pitch)
            pyev.duration = int(bell_e.duration)
            pyev.bell_class = int(bell_e.bell_class)
            pyev.bell_id = int(bell_e.bell_id)
            # no idea why window is not set in XkbBellNotifyEvent
            # since we can fire it from a specific window
            # but we need one for the dispatch logic, so use root if unset
            if bell_e.window!=0:
                verbose("using bell_e.window=%#x", bell_e.window)
                pyev.window = _gw(d, bell_e.window)
            else:
                rw = d.get_default_screen().get_root_window()
                pyev.window = rw
                verbose("bell using root window=%#x", pyev.window)
            pyev.event_only = bool(bell_e.event_only)
            pyev.delivered_to = pyev.window
            pyev.window_model = None
            pyev.bell_name = get_pyatom(d, bell_e.name)
        else:
            log.info("not handled: %s", x_event_type_names.get(etype, etype))
            return None
    except XError as ex:
        log("XError: %s processing %s", ex, event_type, exc_info=True)
        if ex.msg==BadWindow:
            if etype==DestroyNotify:
                #happens too often, don't bother with the debug message
                pass
            else:
                log("Some window in our event disappeared before we could " \
                    + "handle the event %s/%s using %s; so I'm just ignoring it instead. python event=%s", etype, event_type, event_args, pyev)
        else:
            msg = "X11 error %s parsing the event %s/%s using %s; so I'm just ignoring it instead. python event=%s", get_error_text(ex.msg), etype, event_type, event_args, pyev
            log.error(*msg)
        return None
    return pyev


_INIT_X11_FILTER_DONE = False
def init_x11_filter():
    log("init_x11_filter()")
    """ returns True if we did initialize it, False if it was already initialized """
    global _INIT_X11_FILTER_DONE
    if _INIT_X11_FILTER_DONE:
        return False
    init_x11_events()
    gdk_window_add_filter(<cGdkWindow*>0, x_event_filter, <void*>0)
    _INIT_X11_FILTER_DONE = True
    return True

def cleanup_x11_filter():
    log("cleanup_x11_filter()")
    global _INIT_X11_FILTER_DONE
    if not _INIT_X11_FILTER_DONE:
        return False
    gdk_window_remove_filter(<cGdkWindow*>0, x_event_filter, <void*>0)
    _INIT_X11_FILTER_DONE = False
    return True
