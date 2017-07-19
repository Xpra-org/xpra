# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time
import traceback

import gobject
import gtk
import gtk.gdk

from xpra.gtk_common.quit import gtk_main_quit_really
from xpra.gtk_common.error import trap, XError

from xpra.log import Logger
log = Logger("x11", "bindings", "gtk")
verbose = Logger("x11", "bindings", "gtk", "verbose")


from libc.stdint cimport uintptr_t


###################################
# Headers, python magic
###################################
cdef extern from "Python.h":
    ctypedef object PyObject
    object PyBuffer_FromMemory(void *ptr, Py_ssize_t size)
    int PyObject_AsReadBuffer(object obj, void ** buffer, Py_ssize_t * buffer_len) except -1

cdef extern from "string.h":
    void * memcpy( void * destination, void * source, size_t num )

cdef extern from "sys/ipc.h":
    ctypedef struct key_t:
        pass
    key_t IPC_PRIVATE
    int IPC_CREAT

cdef extern from "sys/shm.h":
    int shmget(key_t __key, size_t __size, int __shmflg)
    void *shmat(int __shmid, const void *__shmaddr, int __shmflg)
    int shmdt (const void *__shmaddr)

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
    object pygobject_new(cGObject * contents)

    ctypedef void* gpointer
    ctypedef int GType
    ctypedef struct PyGBoxed:
        #PyObject_HEAD
        gpointer boxed
        GType gtype

cdef cGObject * unwrap(box, pyclass) except? NULL:
    # Extract a raw GObject* from a PyGObject wrapper.
    assert issubclass(pyclass, gobject.GObject)
    if not isinstance(box, pyclass):
        raise TypeError("object %r is not a %r" % (box, pyclass))
    return pygobject_get(box)

# def print_unwrapped(box):
#     "For debugging the above."
#     cdef cGObject * unwrapped
#     unwrapped = unwrap(box, gobject.GObject)
#     if unwrapped == NULL:
#         print("contents is NULL!")
#     else:
#         print("contents is %s" % (<long long>unwrapped))

cdef object wrap(cGObject * contents):
    # Put a raw GObject* into a PyGObject wrapper.
    return pygobject_new(contents)

cdef extern from "glib/gmem.h":
    #void g_free(gpointer mem)
    ctypedef unsigned long gsize
    gpointer g_malloc(gsize n_bytes)



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
    ctypedef struct XFixesCursorNotify:
        char* subtype
        Window XID
        int cursor_serial
        int time
        char* cursor_name
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

    ctypedef unsigned long GdkAtom
    GdkAtom GDK_NONE
    # FIXME: this should have stricter type checking
    GdkAtom PyGdkAtom_Get(object)
    object PyGdkAtom_New(GdkAtom)
    Atom gdk_x11_get_xatom_by_name(char *atom_name)
    GdkAtom gdk_x11_xatom_to_atom_for_display(cGdkDisplay *, Atom)


cdef extern from "gtk-2.0/gtk/gtkselection.h":
    ctypedef int gint
    ctypedef unsigned char guchar
    ctypedef struct GtkSelectionData:
        GdkAtom       selection
        GdkAtom       target
        GdkAtom       type
        gint          format
        guchar        *data
        gint          length
        cGdkDisplay   *display


# Basic utilities:

cdef int get_xwindow(pywindow):
    return GDK_WINDOW_XID(<cGdkWindow*>unwrap(pywindow, gtk.gdk.Window))

def get_pywindow(display_source, xwindow):
    return _get_pywindow(display_source, xwindow)

cdef object _get_pywindow(object display_source, Window xwindow):
    if xwindow==0:
        return None
    disp = get_display_for(display_source)
    win = gtk.gdk.window_foreign_new_for_display(disp, xwindow)
    if win is None:
        verbose("cannot get gdk window for %s : %#x", display_source, xwindow)
        raise XError(BadWindow)
    return win

cpdef get_display_for(obj):
    if obj is None:
        raise TypeError("Cannot get a display: instance is None!")
    if isinstance(obj, gtk.gdk.Display):
        return obj
    elif isinstance(obj, (gtk.gdk.Drawable,
                          gtk.Widget,
                          gtk.Clipboard,
                          gtk.SelectionData,
                          )):
        return obj.get_display()
    else:
        raise TypeError("Don't know how to get a display from %r" % (obj,))

def get_xvisual(pyvisual):
    cdef Visual * xvisual
    xvisual = _get_xvisual(pyvisual)
    if xvisual==NULL:
        return  -1
    return xvisual.visualid

cdef Visual *_get_xvisual(pyvisual):
    return GDK_VISUAL_XVISUAL(<cGdkVisual*>unwrap(pyvisual, gtk.gdk.Visual))


cdef cGdkDisplay * get_raw_display_for(obj) except? NULL:
    return <cGdkDisplay*> unwrap(get_display_for(obj), gtk.gdk.Display)

cdef Display * get_xdisplay_for(obj) except? NULL:
    return GDK_DISPLAY_XDISPLAY(get_raw_display_for(obj))


cdef void * pyg_boxed_get(v):
    cdef PyGBoxed * pygboxed = <PyGBoxed *> v
    return <void *> pygboxed.boxed

def sanitize_gtkselectiondata(obj):
    log("get_gtkselectiondata(%s) type=%s", obj, type(obj))
    cdef GtkSelectionData * selectiondata = <GtkSelectionData *> pyg_boxed_get(obj)
    if selectiondata==NULL:
        return
    log("selectiondata: selection=%s, target=%s, type=%#x, format=%#x, length=%#x, data=%#x",
        selectiondata.selection, selectiondata.target, selectiondata.type, selectiondata.format, selectiondata.length, <uintptr_t> selectiondata.data)
    cdef GdkAtom gdkatom
    cdef gpointer data
    cdef char* c
    if selectiondata.length==-1 and selectiondata.data==NULL:
        log.warn("Warning: sanitizing NULL gtk selection data to avoid crash")
        xatom = get_xatom("STRING")
        gdkatom = get_gdkatom(obj, xatom)
        data = g_malloc(16)
        assert data!=NULL
        c = <char *> data
        for i in range(16):
            c[i] = 0
        selectiondata.length = 0
        selectiondata.format = 8
        selectiondata.type = gdkatom
        selectiondata.data = <guchar*> data


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
    gdkatom = gtk.gdk.atom_intern(str_or_xatom)
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

cpdef get_pyatom(display_source, xatom):
    gdk_atom = get_gdkatom(display_source, xatom)
    if gdk_atom==GDK_NONE:
        return GDK_NONE
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

cpdef get_children(pywindow):
    (pyparent, pychildren) = _query_tree(pywindow)
    return pychildren

def get_parent(pywindow):
    (pyparent, pychildren) = _query_tree(pywindow)
    return pyparent

# Geometry hints

cdef extern from "gtk-2.0/gdk/gdkwindow.h":
    ctypedef struct cGdkGeometry "GdkGeometry":
        int min_width, min_height, max_width, max_height,
        int base_width, base_height, width_inc, height_inc
        double min_aspect, max_aspect
    void gdk_window_constrain_size(cGdkGeometry *geometry,
                                   unsigned int flags, int width, int height,
                                   int * new_width, int * new_height)

def calc_constrained_size(int width, int height, object hints):
    if hints is None:
        return width, height

    cdef cGdkGeometry geom
    cdef int new_width = 0, new_height = 0
    cdef int new_larger_width = 0, new_larger_height = 0
    cdef int flags = 0

    if "maximum-size" in hints:
        flags = flags | gtk.gdk.HINT_MAX_SIZE
        geom.max_width, geom.max_height = hints["maximum-size"]
    if "minimum-size" in hints:
        flags = flags | gtk.gdk.HINT_MIN_SIZE
        geom.min_width, geom.min_height = hints["minimum-size"]
    if "base-size" in hints:
        flags = flags | gtk.gdk.HINT_BASE_SIZE
        geom.base_width, geom.base_height = hints["base-size"]
    if "increment" in hints:
        flags = flags | gtk.gdk.HINT_RESIZE_INC
        geom.width_inc, geom.height_inc = hints["increment"]
    if "min_aspect" in hints:
        assert "max_aspect" in hints
        flags = flags | gtk.gdk.HINT_ASPECT
        geom.min_aspect = hints["min_aspect"]
        geom.max_aspect = hints["max_aspect"]
    gdk_window_constrain_size(&geom, flags, width, height, &new_width, &new_height)
    return new_width, new_height



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
# field of the gtk.gdk.Window's involved.  For the SubstructureRedirect
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
    root = gtk.gdk.get_default_root_window()
    root.set_data(_ev_receiver_key, None)
    for window in get_children(root):
        receivers = window.get_data(_ev_receiver_key)
        if receivers is not None:
            window.set_data(_ev_receiver_key, None)


cdef int CursorNotify = -1
cdef int XKBNotify = -1
cdef int ShapeNotify = -1
_x_event_signals = {}
event_type_names = {}
names_to_event_type = {}
#sometimes we may want to debug routing for certain X11 event types
debug_route_events = []

cpdef get_error_text(code):
    if type(code)!=int:
        return code
    cdef Display * display                              #@DuplicatedSignature
    display = get_xdisplay_for(gtk.gdk.get_default_root_window())
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
    display = gtk.gdk.get_default_root_window().get_display()
    xdisplay = get_xdisplay_for(display)
    if not XkbQueryExtension(xdisplay, &opcode, &event_base, &error_base, &major, &minor):
        log.warn("Warning: Xkb extension is not available")
        return 10000    #should never match any event codes
    verbose("get_XKB_event_base(%s)=%i", display.get_name(), event_base)
    return event_base

cdef int get_XFixes_event_base():
    cdef int event_base = 0                             #@DuplicatedSignature
    cdef int error_base = 0                             #@DuplicatedSignature
    cdef Display * xdisplay                             #@DuplicatedSignature
    display = gtk.gdk.get_default_root_window().get_display()
    xdisplay = get_xdisplay_for(display)
    if not XFixesQueryExtension(xdisplay, &event_base, &error_base):
        log.warn("Warning: XFixes extension is not available")
        return 10000    #should never match any event codes
    verbose("get_XFixes_event_base(%s)=%i", display.get_name(), event_base)
    assert event_base>0, "invalid event base for XFixes"
    return event_base

cdef int get_XDamage_event_base():
    cdef int event_base = 0                             #@DuplicatedSignature
    cdef int error_base = 0                             #@DuplicatedSignature
    cdef Display * xdisplay                             #@DuplicatedSignature
    display = gtk.gdk.get_default_root_window().get_display()
    xdisplay = get_xdisplay_for(display)
    if not XDamageQueryExtension(xdisplay, &event_base, &error_base):
        log.warn("Warning: XDamage extension is not available")
        return 10000    #should never match any event codes
    verbose("get_XDamage_event_base(%s)=%i", display.get_name(), event_base)
    assert event_base>0, "invalid event base for XDamage"
    return event_base

cdef int get_XShape_event_base():
    cdef Display * xdisplay                             #@DuplicatedSignature
    display = gtk.gdk.get_default_root_window().get_display()
    xdisplay = get_xdisplay_for(display)
    cdef int event_base = 0, ignored = 0
    if not XShapeQueryExtension(xdisplay, &event_base, &ignored):
        log.warn("Warning: XShape extension is not available")
        return -1
    return event_base


cdef init_x11_events():
    global _x_event_signals, event_type_names, debug_route_events, XKBNotify, CursorNotify, DamageNotify
    XKBNotify = get_XKB_event_base()
    CursorNotify = XFixesCursorNotify+get_XFixes_event_base()
    DamageNotify = XDamageNotify+get_XDamage_event_base()
    cdef int xshape_base = get_XShape_event_base()
    _x_event_signals = {
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
        CursorNotify        : ("xpra-cursor-event", None),
        XKBNotify           : ("xpra-xkb-event", None),
        DamageNotify        : ("xpra-damage-event", None),
        EnterNotify         : ("xpra-enter-event", None),
        LeaveNotify         : ("xpra-leave-event", None),
        MotionNotify        : ("xpra-motion-event", None)       #currently unused, just defined for debugging purposes
        }
    event_type_names = {
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
        XKBNotify           : "XKBNotify",
        CursorNotify        : "CursorNotify",
        DamageNotify        : "DamageNotify",
        #GenericEvent        : "GenericEvent",    #Old versions of X11 don't have this defined, ignore it
        }
    if xshape_base>=0:
        global ShapeNotify
        ShapeNotify = xshape_base
        _x_event_signals[ShapeNotify] = ("xpra-shape-event", None)
        event_type_names[ShapeNotify] = "ShapeNotify"
        log("added ShapeNotify=%s", ShapeNotify)
    for k,v in event_type_names.items():
        names_to_event_type[v] = k
    verbose("x_event_signals=%s", _x_event_signals)
    verbose("event_type_names=%s", event_type_names)
    verbose("names_to_event_type=%s", names_to_event_type)

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
            log.warn("unknown X11 debug event type: %s", name)
            continue
        #add to correct set:
        for e in events:
            event_set.add(e)
    events = debug_set.difference(ignore_set)
    if len(events)>0:
        log.warn("debugging of X11 events enabled for: %s", ", ".join(events))
    debug_route_events = [names_to_event_type.get(x) for x in events]

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

cdef _maybe_send_event(DEBUG, handlers, signal, event, hinfo="window"):
    if not handlers:
        if DEBUG:
            log.info("  no handler registered for %s (%s), ignoring event", hinfo, handlers)
        return
    # Copy the 'handlers' list, because signal handlers might cause items
    # to be added or removed from it while we are iterating:
    for handler in list(handlers):
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

cdef _route_event(event, signal, parent_signal):
    # Sometimes we get GDK events with event.window == None, because they are
    # for windows we have never created a GdkWindow object for, and GDK
    # doesn't do so just for this event.  As far as I can tell this only
    # matters for override redirect windows when they disappear, and we don't
    # care about those anyway.
    global debug_route_events
    DEBUG = event.type in debug_route_events
    if DEBUG:
        log.info("%s event %#x : %s", event_type_names.get(event.type, event.type), event.serial, event)
    handlers = None
    if event.window is None:
        if DEBUG:
            log.info("  event.window is None, ignoring")
        assert event.type in (UnmapNotify, DestroyNotify), \
                "event window is None for event type %s!" % (event_type_names.get(event.type, event.type))
    elif event.window is event.delivered_to:
        if signal is not None:
            window = event.window
            if DEBUG:
                log.info("  delivering event to window itself: %#x  (signal=%s)", window.xid, signal)
            handlers = window.get_data(_ev_receiver_key)
            _maybe_send_event(DEBUG, handlers, signal, event, "window %s" % window.xid)
        elif DEBUG:
            log.info("  received event on window itself but have no signal for that")
    else:
        if parent_signal is not None:
            window = event.delivered_to
            if DEBUG:
                log.info("  delivering event to parent window: %#x (signal=%s)", window.xid, parent_signal)
            handlers = window.get_data(_ev_receiver_key)
            _maybe_send_event(DEBUG, handlers, parent_signal, event, "parent window %s" % window.xid)
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
    gtk.gdk.error_trap_push()
    try:
        disp = get_display_for(display)
        win = gtk.gdk.window_foreign_new_for_display(disp, xwin)
        gtk.gdk.flush()
        error = gtk.gdk.error_trap_pop()
    except Exception as e:
        verbose("cannot get gdk window for %s, %s: %s", display, xwin, e)
        error = gtk.gdk.error_trap_pop()
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


# Just to make it easier to pass around and have a helpful debug logging.
# Really, just a python objects where we can stick random bags of attributes.
class X11Event(object):

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        d = {}
        for k,v in self.__dict__.items():
            if k=="name":
                continue
            elif k=="serial":
                d[k] = "%#x" % v
            elif v and type(v)==gtk.gdk.Window:
                d[k] = "%#x" % v.xid
            elif v and type(v)==gtk.gdk.Display:
                d[k] = "%s" % v.get_name()
            else:
                d[k] = v
        return "<X11:%s %r>" % (self.name, d)


cdef GdkFilterReturn x_event_filter(GdkXEvent * e_gdk,
                                    GdkEvent * gdk_event,
                                    void * userdata) with gil:
    cdef XEvent * e
    cdef XDamageNotifyEvent * damage_e
    cdef XFixesCursorNotifyEvent * cursor_e
    cdef XkbAnyEvent * xkb_e
    cdef XkbBellNotifyEvent * bell_e
    cdef XShapeEvent * shape_e
    cdef double start
    cdef object my_events
    cdef object event_args
    cdef object d
    cdef object pyev
    e = <XEvent*>e_gdk
    event_type = event_type_names.get(e.type, e.type)
    if e.xany.send_event and e.type not in (ClientMessage, UnmapNotify):
        log("x_event_filter ignoring %s send_event", event_type)
        return GDK_FILTER_CONTINUE
    start = time.time()
    try:
        my_events = _x_event_signals
        event_args = my_events.get(e.type)
        log("x_event_filter event=%s/%s window=%#x", event_args, event_type, e.xany.window)
        if event_args is not None:
            d = wrap(<cGObject*>gdk_x11_lookup_xdisplay(e.xany.display))
            pyev = X11Event(event_type)
            pyev.type = e.type
            pyev.send_event = e.xany.send_event
            pyev.display = d
            pyev.serial = e.xany.serial
            # Unmarshal:
            try:
                if e.type != XKBNotify:
                    pyev.delivered_to = _gw(d, e.xany.window)

                if e.type == DamageNotify:
                    damage_e = <XDamageNotifyEvent*>e
                    pyev.window = _gw(d, e.xany.window)
                    pyev.damage = damage_e.damage
                    pyev.x = damage_e.area.x
                    pyev.y = damage_e.area.y
                    pyev.width = damage_e.area.width
                    pyev.height = damage_e.area.height
                elif e.type == MapRequest:
                    pyev.window = _gw(d, e.xmaprequest.window)
                elif e.type == ConfigureRequest:
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
                elif e.type == ResizeRequest:
                    pyev.window = _gw(d, e.xresizerequest.window)
                    pyev.width = e.xresizerequest.width
                    pyev.height = e.xresizerequest.height
                elif e.type in (FocusIn, FocusOut):
                    pyev.window = _gw(d, e.xfocus.window)
                    pyev.mode = e.xfocus.mode
                    pyev.detail = e.xfocus.detail
                elif e.type in (EnterNotify, LeaveNotify):
                    pyev.window = _gw(d, e.xcrossing.window)
                    pyev.mode = e.xcrossing.mode
                    pyev.detail = e.xcrossing.detail
                    pyev.subwindow = _gw(d, e.xcrossing.subwindow)
                    pyev.focus = e.xcrossing.focus
                elif e.type == ClientMessage:
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
                elif e.type == CreateNotify:
                    pyev.window = _gw(d, e.xcreatewindow.window)
                    pyev.width = e.xcreatewindow.width
                    pyev.height = e.xcreatewindow.height
                elif e.type == MapNotify:
                    pyev.window = _gw(d, e.xmap.window)
                    pyev.override_redirect = e.xmap.override_redirect
                elif e.type == UnmapNotify:
                    pyev.window = _gw(d, e.xunmap.window)
                elif e.type == DestroyNotify:
                    pyev.window = _gw(d, e.xdestroywindow.window)
                elif e.type == PropertyNotify:
                    pyev.window = _gw(d, e.xany.window)
                    pyev.atom = trap.call_synced(get_pyatom, d, e.xproperty.atom)
                elif e.type == ConfigureNotify:
                    pyev.window = _gw(d, e.xconfigure.window)
                    pyev.x = e.xconfigure.x
                    pyev.y = e.xconfigure.y
                    pyev.width = e.xconfigure.width
                    pyev.height = e.xconfigure.height
                    pyev.border_width = e.xconfigure.border_width
                    pyev.above = e.xconfigure.above
                elif e.type == CirculateNotify:
                    pyev.window = _gw(d, e.xcirculaterequest.window)
                    pyev.place = e.xcirculaterequest.place
                elif e.type == ReparentNotify:
                    pyev.window = _gw(d, e.xreparent.window)
                elif e.type == KeyPress:
                    pyev.window = _gw(d, e.xany.window)
                    pyev.hardware_keycode = e.xkey.keycode
                    pyev.state = e.xkey.state
                elif e.type == CursorNotify:
                    pyev.window = _gw(d, e.xany.window)
                    cursor_e = <XFixesCursorNotifyEvent*>e
                    pyev.cursor_serial = cursor_e.cursor_serial
                    pyev.cursor_name = trap.call_synced(get_pyatom, d, cursor_e.cursor_name)
                elif e.type == MotionNotify:
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
                elif e.type == ShapeNotify:
                    shape_e = <XShapeEvent*> e
                    pyev.window = _gw(d, shape_e.window)
                    pyev.kind = shape_e.kind
                    pyev.x = shape_e.x
                    pyev.y = shape_e.y
                    pyev.width = shape_e.width
                    pyev.height = shape_e.height
                    pyev.shaped = shape_e.shaped
                elif e.type == XKBNotify:
                    # note we could just cast directly to XkbBellNotifyEvent
                    # but this would be dirty, and we may want to catch
                    # other types of XKB events in the future
                    xkb_e = <XkbAnyEvent*>e
                    verbose("XKBNotify event received xkb_type=%s", xkb_e.xkb_type)
                    if xkb_e.xkb_type!=XkbBellNotify:
                        return GDK_FILTER_CONTINUE
                    bell_e = <XkbBellNotifyEvent*>e
                    pyev.type = "bell"
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
                    log.info("not handled: %s", event_type_names.get(e.type, e.type))
            except XError as ex:
                if ex.msg==BadWindow:
                    if e.type == DestroyNotify:
                        #happens too often, don't bother with the debug message
                        pass
                    else:
                        log("Some window in our event disappeared before we could " \
                            + "handle the event %s/%s using %s; so I'm just ignoring it instead. python event=%s", e.type, event_type, event_args, pyev)
                else:
                    msg = "X11 error %s parsing the event %s/%s using %s; so I'm just ignoring it instead. python event=%s", get_error_text(ex.msg), e.type, event_type, event_args, pyev
                    log.error(*msg)
            else:
                signal, parent_signal = event_args
                _route_event(pyev, signal, parent_signal)
        log("x_event_filter event=%s/%s took %.1fms", event_args, event_type, 1000.0*(time.time()-start))
    except (KeyboardInterrupt, SystemExit):
        verbose("exiting on KeyboardInterrupt/SystemExit")
        gtk_main_quit_really()
    except:
        log.warn("Unhandled exception in x_event_filter:", exc_info=True)
    return GDK_FILTER_CONTINUE


_INIT_X11_FILTER_DONE = False
def init_x11_filter():
    """ returns True if we did initialize it, False if it was already initialized """
    global _INIT_X11_FILTER_DONE
    if _INIT_X11_FILTER_DONE:
        return False
    init_x11_events()
    gdk_window_add_filter(<cGdkWindow*>0, x_event_filter, <void*>0)
    _INIT_X11_FILTER_DONE = True
    return True

def cleanup_x11_filter():
    global _INIT_X11_FILTER_DONE
    if not _INIT_X11_FILTER_DONE:
        return False
    gdk_window_remove_filter(<cGdkWindow*>0, x_event_filter, <void*>0)
    _INIT_X11_FILTER_DONE = False
    return True
