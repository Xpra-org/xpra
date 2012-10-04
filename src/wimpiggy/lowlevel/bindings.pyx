# This file is part of Parti.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Monolithic file containing simple Pyrex wrappers for otherwise unexposed
# GDK, GTK, and X11 primitives, plus utility functions for writing same.
# Really this should be split up, but I haven't figured out how Pyrex's
# cimport stuff works yet.

import struct

import gobject
import gtk
import gtk.gdk

from wimpiggy.util import dump_exc, AdHocStruct, gtk_main_quit_really
from wimpiggy.error import trap, XError

from wimpiggy.log import Logger
log = Logger("wimpiggy.lowlevel")

###################################
# Headers, python magic
###################################
cdef extern from "stdlib.h":
    void* malloc(size_t __size)
    void free(void* mem)

cdef extern from "X11/Xutil.h":
    pass

cdef extern from "gdk/gdk.h":
    pass
cdef extern from "gdk/gdkx.h":
    pass

cdef extern from "Python.h":
    object PyString_FromStringAndSize(char * s, int len)
    ctypedef int Py_ssize_t
    int PyObject_AsWriteBuffer(object obj,
                               void ** buffer,
                               Py_ssize_t * buffer_len) except -1
    int PyObject_AsReadBuffer(object obj,
                              void ** buffer,
                              Py_ssize_t * buffer_len) except -1

# Serious black magic happens here (I owe these guys beers):
cdef extern from "pygobject.h":
    void init_pygobject()
init_pygobject()

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
    ctypedef void** const_void_pp "const void**"
    object pygobject_new(cGObject * contents)

    # I am naughty; the exposed accessor for PyGBoxed objects is a macro that
    # takes a type name as one of its arguments, and thus is impossible to
    # wrap from Pyrex; so I just peek into the object directly:
    ctypedef struct PyGBoxed:
        void * boxed

cdef cGObject * unwrap(box, pyclass) except? NULL:
    # Extract a raw GObject* from a PyGObject wrapper.
    assert issubclass(pyclass, gobject.GObject)
    if not isinstance(box, pyclass):
        raise TypeError, ("object %r is not a %r" % (box, pyclass))
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

cdef void * unwrap_boxed(box, pyclass):
    # Extract a raw object from a PyGBoxed wrapper
    assert issubclass(pyclass, gobject.GBoxed)
    if not isinstance(box, pyclass):
        raise TypeError, ("object %r is not a %r" % (box, pyclass))
    return (<PyGBoxed *>box).boxed

###################################
# Simple speed-up code
###################################

def premultiply_argb_in_place(buf):
    # b is a Python buffer object, containing non-premultiplied ARGB32 data in
    # native-endian.
    # We convert to premultiplied ARGB32 data, in-place.
    cdef unsigned int * cbuf = <unsigned int *> 0
    cdef Py_ssize_t cbuf_len = 0
    cdef unsigned int a, r, g, b
    assert sizeof(int) == 4
    PyObject_AsWriteBuffer(buf, <void **>&cbuf, &cbuf_len)
    cdef int i
    for 0 <= i < cbuf_len / 4:
        a = (cbuf[i] >> 24) & 0xff
        r = (cbuf[i] >> 16) & 0xff
        r = (r * a) / 255
        g = (cbuf[i] >> 8) & 0xff
        g = g * a / 255
        b = (cbuf[i] >> 0) & 0xff
        b = b * a / 255
        cbuf[i] = (a << 24) | (r << 16) | (g << 8) | (b << 0)

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
    # really is 64 bits on 64-bit systems.  Why?  I have no idea.)
    ctypedef CARD32 XID

    ctypedef int Bool
    ctypedef int Status
    ctypedef CARD32 Atom
    ctypedef XID Drawable
    ctypedef XID Window
    ctypedef XID Pixmap
    ctypedef XID KeySym
    ctypedef CARD32 Time

    int XFree(void * data)

    # Needed to find the secret window Gtk creates to own the selection, so we
    # can broadcast it:
    Window XGetSelectionOwner(Display * display, Atom selection)

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
    ctypedef struct XReparentEvent:
        Window window
        Window parent
        int x, y
    ctypedef struct XCirculateRequestEvent:
        Window parent  # Same as xany.window, confusingly.
        Window window
        int place
    # Focus handling
    ctypedef struct XFocusChangeEvent:
        Window window
        int mode, detail
    # We have to generate synthetic ConfigureNotify's:
    ctypedef struct XConfigureEvent:
        Window event    # Same as xany.window, confusingly.
                        # The selected-on window.
        Window window   # The effected window.
        int x, y, width, height, border_width
        Window above
        Bool override_redirect
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
    ctypedef union XEvent:
        int type
        XAnyEvent xany
        XMapRequestEvent xmaprequest
        XConfigureRequestEvent xconfigurerequest
        XCirculateRequestEvent xcirculaterequest
        XConfigureEvent xconfigure
        XFocusChangeEvent xfocus
        XClientMessageEvent xclient
        XMapEvent xmap
        XUnmapEvent xunmap
        XReparentEvent xreparent
        XDestroyWindowEvent xdestroywindow
        XPropertyEvent xproperty
        XKeyEvent xkey

    Status XSendEvent(Display *, Window target, Bool propagate,
                      unsigned long event_mask, XEvent * event)

    int XSelectInput(Display * display, Window w, unsigned long event_mask)

    int cXChangeProperty "XChangeProperty" \
        (Display *, Window w, Atom property,
         Atom type, int format, int mode, unsigned char * data, int nelements)
    int cXGetWindowProperty "XGetWindowProperty" \
        (Display * display, Window w, Atom property,
         long offset, long length, Bool delete,
         Atom req_type, Atom * actual_type,
         int * actual_format,
         unsigned long * nitems, unsigned long * bytes_after,
         unsigned char ** prop)
    int cXDeleteProperty "XDeleteProperty" \
        (Display * display, Window w, Atom property)


    int cXAddToSaveSet "XAddToSaveSet" (Display *, Window w)
    int cXRemoveFromSaveSet "XRemoveFromSaveSet" (Display *, Window w)

    ctypedef struct XWindowAttributes:
        int x, y, width, height, border_width
        Bool override_redirect
        int map_state
        unsigned long your_event_mask
    Status XGetWindowAttributes(Display * display, Window w,
                                XWindowAttributes * attributes)

    ctypedef struct XWindowChanges:
        int x, y, width, height, border_width
        Window sibling
        int stack_mode
    int cXConfigureWindow "XConfigureWindow" \
        (Display * display, Window w,
         unsigned int value_mask, XWindowChanges * changes)

    Bool XTranslateCoordinates(Display * display,
                               Window src_w, Window dest_w,
                               int src_x, int src_y,
                               int * dest_x, int * dest_y,
                               Window * child)

    Status XQueryTree(Display * display, Window w,
                      Window * root, Window * parent,
                      Window ** children, unsigned int * nchildren)

    int cXSetInputFocus "XSetInputFocus" (Display * display, Window focus,
                                          int revert_to, Time time)
    # Debugging:
    int cXGetInputFocus "XGetInputFocus" (Display * display, Window * focus,
                                          int * revert_to)

    # Keyboard bindings
    ctypedef unsigned char KeyCode
    ctypedef struct XModifierKeymap:
        int max_keypermod
        KeyCode * modifiermap # an array with 8*max_keypermod elements
    XModifierKeymap* XGetModifierMapping(Display* display)
    int XFreeModifiermap(XModifierKeymap* modifiermap)
    int XDisplayKeycodes(Display* display, int* min_keycodes, int* max_keycodes)
    KeySym XStringToKeysym(char* string)
    KeySym* XGetKeyboardMapping(Display* display, KeyCode first_keycode, int keycode_count, int* keysyms_per_keycode_return)
    int XChangeKeyboardMapping(Display* display, int first_keycode, int keysyms_per_keycode, KeySym* keysyms, int num_codes)
    XModifierKeymap* XInsertModifiermapEntry(XModifierKeymap* modifiermap, KeyCode keycode_entry, int modifier)
    KeySym XKeycodeToKeysym(Display* display, KeyCode keycode, int index)
    KeySym XStringToKeysym(char* string)
    char* XKeysymToString(KeySym keysym)

    int XChangeKeyboardMapping(Display* display, int first_keycode, int keysyms_per_keycode, KeySym* keysyms, int num_codes)
    int XSetModifierMapping(Display* display, XModifierKeymap* modifiermap)

    int XGrabKey(Display * display, int keycode, unsigned int modifiers,
                 Window grab_window, Bool owner_events,
                 int pointer_mode, int keyboard_mode)
    int XUngrabKey(Display * display, int keycode, unsigned int modifiers,
                   Window grab_window)
    int XQueryKeymap(Display * display, char [32] keys_return)

    # XKillClient
    int cXKillClient "XKillClient" (Display *, XID)

    # XUnmapWindow
    int XUnmapWindow(Display *, Window)
    unsigned long NextRequest(Display *)

    # XMapWindow
    int XMapWindow(Display *, Window)

    ctypedef struct XRectangle:
        short x, y
        unsigned short width, height


######
# GDK primitives, and wrappers for Xlib
######

# gdk_region_get_rectangles (pygtk bug #517099)
cdef extern from "gtk-2.0/gdk/gdktypes.h":
    ctypedef struct GdkRegion:
        pass
    ctypedef struct GdkRectangle:
        int x, y, width, height
    void gdk_region_get_rectangles(GdkRegion *, GdkRectangle **, int *)
    void g_free(void *)

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

# Basic utilities:

def get_xwindow(pywindow):
    return GDK_WINDOW_XID(<cGdkWindow*>unwrap(pywindow, gtk.gdk.Window))

def get_pywindow(display_source, xwindow):
    disp = get_display_for(display_source)
    win = gtk.gdk.window_foreign_new_for_display(disp, xwindow)
    if win is None:
        log.warn("cannot get gdk window for %s : %s", display_source, xwindow)
        raise XError(BadWindow)
    return win

def get_display_for(obj):
    if obj is None:
        raise TypeError("Cannot get a display: instance is None!")
    if isinstance(obj, gtk.gdk.Display):
        return obj
    elif isinstance(obj, (gtk.gdk.Drawable,
                          gtk.Widget,
                          gtk.Clipboard)):
        return obj.get_display()
    else:
        raise TypeError("Don't know how to get a display from %r" % (obj,))

cdef cGdkDisplay * get_raw_display_for(obj) except? NULL:
    return <cGdkDisplay*> unwrap(get_display_for(obj), gtk.gdk.Display)

cdef Display * get_xdisplay_for(obj) except? NULL:
    return GDK_DISPLAY_XDISPLAY(get_raw_display_for(obj))


def get_xatom(str_or_xatom):
    """Returns the X atom corresponding to the given Python string or Python
    integer (assumed to already be an X atom)."""
    if isinstance(str_or_xatom, (int, long)):
        return str_or_xatom
    assert isinstance(str_or_xatom, str)
    gdkatom = gtk.gdk.atom_intern(str_or_xatom)
    if not gdkatom:
        return  0
    return gdk_x11_get_xatom_by_name(str_or_xatom)

def get_pyatom(display_source, xatom):
    if long(xatom) > long(2) ** 32:
        raise Exception, "weirdly huge purported xatom: %s" % xatom
    if xatom==0:
        return  None
    cdef cGdkDisplay * disp
    cdef GdkAtom gdk_atom
    disp = get_raw_display_for(display_source)
    gdk_atom = gdk_x11_xatom_to_atom_for_display(disp, xatom)
    if gdk_atom==GDK_NONE:
        return  None
    return str(PyGdkAtom_New(gdk_atom))



# Property handling:

# (Note: GDK actually has a wrapper for the Xlib property API,
# gdk_property_{get,change,delete}.  However, the documentation for
# gtk_property_get says "gtk_property_get() makes the situation worse...the
# semantics should be considered undefined...You are advised to use
# XGetWindowProperty() directly".  In light of this, we just ignore the GDK
# property API and use the Xlib functions directly.)

def _munge_packed_ints_to_longs(data):
    assert len(data) % sizeof(int) == 0
    n = len(data) / sizeof(int)
    format_from = "@" + "i" * n
    format_to = "@" + "l" * n
    return struct.pack(format_to, *struct.unpack(format_from, data))

def XChangeProperty(pywindow, property, value):
    "Set a property on a window."
    (type, format, data) = value
    assert format in (8, 16, 32), "invalid format for property: %s" % format
    assert (len(data) % (format / 8)) == 0, "size of data is not a multiple of %s" % (format/8)
    nitems = len(data) / (format / 8)
    if format == 32:
        data = _munge_packed_ints_to_longs(data)
    cdef char * data_str
    data_str = data
    cXChangeProperty(get_xdisplay_for(pywindow),
                     get_xwindow(pywindow),
                     get_xatom(property),
                     get_xatom(type),
                     format,
                     PropModeReplace,
                     <unsigned char *>data_str,
                     nitems)

def _munge_packed_longs_to_ints(data):
    assert len(data) % sizeof(long) == 0
    n = len(data) / sizeof(long)
    format_from = "@" + "l" * n
    format_to = "@" + "i" * n
    return struct.pack(format_to, *struct.unpack(format_from, data))

class PropertyError(Exception):
    pass
class BadPropertyType(PropertyError):
    pass
class PropertyOverflow(PropertyError):
    pass
class NoSuchProperty(PropertyError):
    pass
def XGetWindowProperty(pywindow, property, req_type):
    # NB: Accepts req_type == 0 for AnyPropertyType
    # "64k is enough for anybody"
    # (Except, I've found window icons that are strictly larger, hence the
    # added * 5...)
    buffer_size = 64 * 1024 * 5
    cdef Atom xactual_type = <Atom> 0
    cdef int actual_format = 0
    cdef unsigned long nitems = 0, bytes_after = 0
    cdef unsigned char * prop = <unsigned char*> 0
    cdef Status status
    xreq_type = get_xatom(req_type)
    # This is the most bloody awful API I have ever seen.  You will probably
    # not be able to understand this code fully without reading
    # XGetWindowProperty's man page at least 3 times, slowly.
    status = cXGetWindowProperty(get_xdisplay_for(pywindow),
                                 get_xwindow(pywindow),
                                 get_xatom(property),
                                 0,
                                 # This argument has to be divided by 4.  Thus
                                 # speaks the spec.
                                 buffer_size / 4,
                                 False,
                                 xreq_type, &xactual_type,
                                 &actual_format, &nitems, &bytes_after, &prop)
    if status != Success:
        raise PropertyError, "no such window"
    if xactual_type == XNone:
        raise NoSuchProperty, property
    if xreq_type and xreq_type != xactual_type:
        raise BadPropertyType, xactual_type
    # This should only occur for bad property types:
    assert not (bytes_after and not nitems)
    # actual_format is in (8, 16, 32), and is the number of bits in a logical
    # element.  However, this doesn't mean that each element is stored in that
    # many bits, oh no.  On a 32-bit machine it is, but on a 64-bit machine,
    # iff the output array contains 32-bit integers, than each one is given
    # 64-bits of space.
    assert actual_format > 0
    if actual_format == 8:
        bytes_per_item = 1
    elif actual_format == 16:
        bytes_per_item = sizeof(short)
    elif actual_format == 32:
        bytes_per_item = sizeof(long)
    else:
        assert False
    nbytes = bytes_per_item * nitems
    if bytes_after:
        raise PropertyOverflow, nbytes + bytes_after
    data = PyString_FromStringAndSize(<char *>prop, nbytes)
    XFree(prop)
    if actual_format == 32:
        return _munge_packed_longs_to_ints(data)
    else:
        return data

def XDeleteProperty(pywindow, property):
    cXDeleteProperty(get_xdisplay_for(pywindow),
                     get_xwindow(pywindow),
                     get_xatom(property))

# Save set handling
def XAddToSaveSet(pywindow):
    cXAddToSaveSet(get_xdisplay_for(pywindow),
                   get_xwindow(pywindow))

def XRemoveFromSaveSet(pywindow):
    cXRemoveFromSaveSet(get_xdisplay_for(pywindow),
                        get_xwindow(pywindow))

# Children listing
def _query_tree(pywindow):
    cdef Window root = 0, parent = 0
    cdef Window * children = <Window *> 0
    cdef unsigned int nchildren = 0
    if not XQueryTree(get_xdisplay_for(pywindow),
                      get_xwindow(pywindow),
                      &root, &parent, &children, &nchildren):
        return (None, [])
    pychildren = []
    for i from 0 <= i < nchildren:
        #we cannot get the gdk window for wid=0
        if children[i]>0:
            pychildren.append(get_pywindow(pywindow, children[i]))
    # Apparently XQueryTree sometimes returns garbage in the 'children'
    # pointer when 'nchildren' is 0, which then leads to a segfault when we
    # try to XFree the non-NULL garbage.
    if nchildren > 0 and children != NULL:
        XFree(children)
    if parent != XNone:
        pyparent = get_pywindow(pywindow, parent)
    else:
        pyparent = None
    return (pyparent, pychildren)

def get_children(pywindow):
    (pyparent, pychildren) = _query_tree(pywindow)
    return pychildren

def get_parent(pywindow):
    (pyparent, pychildren) = _query_tree(pywindow)
    return pyparent

# Mapped status
def is_mapped(pywindow):
    cdef XWindowAttributes attrs
    XGetWindowAttributes(get_xdisplay_for(pywindow),
                         get_xwindow(pywindow),
                         &attrs)
    return attrs.map_state != IsUnmapped

# Override-redirect status
def is_override_redirect(pywindow):
    cdef XWindowAttributes or_attrs
    XGetWindowAttributes(get_xdisplay_for(pywindow),
                         get_xwindow(pywindow),
                         &or_attrs)
    return or_attrs.override_redirect

def geometry_with_border(pywindow):
    cdef XWindowAttributes geom_attrs
    XGetWindowAttributes(get_xdisplay_for(pywindow),
                         get_xwindow(pywindow),
                         &geom_attrs)
    return (geom_attrs.x, geom_attrs.y, geom_attrs.width, geom_attrs.height, geom_attrs.border_width)

# Focus management
def XSetInputFocus(pywindow, time=None):
    # Always does RevertToParent
    if time is None:
        time = CurrentTime
    cXSetInputFocus(get_xdisplay_for(pywindow),
                    get_xwindow(pywindow),
                    RevertToParent,
                    time)
    printFocus(pywindow)

def printFocus(display_source):
    # Debugging
    cdef Window w = 0
    cdef int revert_to = 0
    cXGetInputFocus(get_xdisplay_for(display_source), &w, &revert_to)
    log("Current focus: %s, %s", hex(w), revert_to)

# Geometry hints

cdef extern from "gtk-2.0/gdk/gdkwindow.h":
    ctypedef struct cGdkGeometry "GdkGeometry":
        int min_width, min_height, max_width, max_height,
        int base_width, base_height, width_inc, height_inc
        double min_aspect, max_aspect
    void gdk_window_constrain_size(cGdkGeometry *geometry,
                                   unsigned int flags, int width, int height,
                                   int * new_width, int * new_height)

def calc_constrained_size(width, height, hints):
    if hints is None:
        return (width, height, width, height)

    cdef cGdkGeometry geom
    cdef int new_width = 0, new_height = 0
    flags = 0

    if hints.max_size is not None:
        flags = flags | gtk.gdk.HINT_MAX_SIZE
        geom.max_width, geom.max_height = hints.max_size
    if hints.min_size is not None:
        flags = flags | gtk.gdk.HINT_MIN_SIZE
        geom.min_width, geom.min_height = hints.min_size
    if hints.base_size is not None:
        flags = flags | gtk.gdk.HINT_BASE_SIZE
        geom.base_width, geom.base_height = hints.base_size
    if hints.resize_inc is not None:
        flags = flags | gtk.gdk.HINT_RESIZE_INC
        geom.width_inc, geom.height_inc = hints.resize_inc
    if hints.min_aspect is not None:
        assert hints.max_aspect is not None
        flags = flags | gtk.gdk.HINT_ASPECT
        geom.min_aspect = hints.min_aspect
        geom.max_aspect = hints.max_aspect
    gdk_window_constrain_size(&geom, flags, width, height,
                              &new_width, &new_height)

    vis_width, vis_height = (new_width, new_height)
    if hints.resize_inc is not None:
        if hints.base_size is not None:
            vis_width = vis_width - hints.base_size[0]
            vis_height = vis_height - hints.base_size[1]
        vis_width = vis_width / hints.resize_inc[0]
        vis_height = vis_height / hints.resize_inc[1]

    return (new_width, new_height, vis_width, vis_height)


def get_rectangle_from_region(region):
    cdef GdkRegion * cregion
    cdef GdkRectangle * rectangles = <GdkRectangle*> 0
    cdef int count = 0
    cregion = <GdkRegion *>unwrap_boxed(region, gtk.gdk.Region)
    gdk_region_get_rectangles(cregion, &rectangles, &count)
    if count == 0:
        g_free(rectangles)
        raise ValueError, "empty region"
    (x, y, w, h) = (rectangles[0].x, rectangles[0].y,
                    rectangles[0].width, rectangles[0].height)
    g_free(rectangles)
    return (x, y, w, h)

###################################
# Keyboard binding
###################################

def get_modifier_map(display_source):
    cdef XModifierKeymap * xmodmap
    xmodmap = XGetModifierMapping(get_xdisplay_for(display_source))
    try:
        keycode_array = []
        for i in range(8 * xmodmap.max_keypermod):
            keycode_array.append(xmodmap.modifiermap[i])
        return (xmodmap.max_keypermod, keycode_array)
    finally:
        XFreeModifiermap(xmodmap)

# xmodmap's "keycode" action done implemented in python
# some of the methods aren't very pythonic
# that's intentional so as to keep as close as possible
# to the original C xmodmap code

min_keycode = -1
max_keycode = -1
cdef _get_minmax_keycodes(Display *display):
    cdef int cmin_keycode, cmax_keycode
    global min_keycode, max_keycode
    if min_keycode==-1 and max_keycode==-1:
        XDisplayKeycodes(display, &cmin_keycode, &cmax_keycode)
        min_keycode = cmin_keycode
        max_keycode = cmax_keycode
    return min_keycode, max_keycode

def get_minmax_keycodes():
    cdef Display * display
    display = get_xdisplay_for(gtk.gdk.get_default_root_window())
    return  _get_minmax_keycodes(display)

cdef XModifierKeymap* work_keymap = NULL
cdef XModifierKeymap* get_keymap(Display * display, load):
    global work_keymap
    if work_keymap==NULL and load:
        log("retrieving keymap")
        work_keymap = XGetModifierMapping(display)
    return work_keymap

cdef set_keymap(XModifierKeymap* new_keymap):
    global work_keymap
    log("setting new keymap")
    work_keymap = new_keymap

cdef _parse_keysym(symbol):
    cdef KeySym keysym
    if symbol in ["NoSymbol", "VoidSymbol"]:
        return  NoSymbol
    keysym = XStringToKeysym(symbol)
    if keysym==NoSymbol:
        if symbol.lower().startswith("0x"):
            return int(symbol, 16)
        if symbol[0] in ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]:
            return int(symbol)
        return  None
    return keysym

def parse_keysym(symbol):
    return _parse_keysym(symbol)

cdef _keysym_str(keysym_val):
    cdef KeySym keysym                      #@DuplicatedSignature
    keysym = int(keysym_val)
    s = XKeysymToString(keysym)
    return s

def keysym_str(keysym_val):
    return _keysym_str(keysym_val)

def get_keysym_list(symbols):
    """ convert a list of key symbols into a list of KeySym values
        by calling parse_keysym on each one
    """
    keysymlist = []
    for x in symbols:
        keysym = _parse_keysym(x)
        if keysym is not None:
            keysymlist.append(keysym)
    return keysymlist

cdef _parse_keycode(Display* display, keycode_str):
    if keycode_str=="any":
        #find a free one:
        keycode = 0
    elif keycode_str[:1]=="x":
        #int("0x101", 16)=257
        keycode = int("0"+keycode_str, 16)
    else:
        keycode = int(keycode_str)
    min_keycode, max_keycode = _get_minmax_keycodes(display)
    if keycode!=0 and keycode<min_keycode or keycode>max_keycode:
        log.error("keycode %s: value %s is out of range (%s-%s)", keycode_str, keycode, min_keycode, max_keycode)
        return -1
    return keycode

def parse_keycode(display_source, keycode_str):
    cdef Display * display                  #@DuplicatedSignature
    display = get_xdisplay_for(display_source)
    return _parse_keycode(display, keycode_str)

cdef xmodmap_setkeycodes(Display* display, keycodes, new_keysyms):
    cdef KeySym keysym                      #@DuplicatedSignature
    cdef KeySym* ckeysyms
    cdef int num_codes
    cdef int keysyms_per_keycode
    cdef first_keycode
    first_keycode = min(keycodes.keys())
    last_keycode = max(keycodes.keys())
    num_codes = 1+last_keycode-first_keycode
    MAX_KEYSYMS_PER_KEYCODE = 8
    keysyms_per_keycode = min(MAX_KEYSYMS_PER_KEYCODE, max([1]+[len(keysyms) for keysyms in keycodes.values()]))
    log("xmodmap_setkeycodes using %s keysyms_per_keycode", keysyms_per_keycode)
    ckeysyms = <KeySym*> malloc(sizeof(KeySym)*num_codes*keysyms_per_keycode)
    try:
        missing_keysyms = []
        for i in range(0, num_codes):
            keycode = first_keycode+i
            keysyms_strs = keycodes.get(keycode)
            log("setting keycode %s: %s", keycode, keysyms_strs)
            if keysyms_strs is None:
                if len(new_keysyms)>0:
                    #no keysyms for this keycode yet, assign one of the "new_keysyms"
                    keysyms = new_keysyms[:1]
                    new_keysyms = new_keysyms[1:]
                    log("assigned keycode %s to %s", keycode, keysyms[0])
                else:
                    keysyms = []
                    log("keycode %s is still free", keycode)
            else:
                keysyms = []
                for ks in keysyms_strs:
                    if ks in (None, ""):
                        k = None
                    elif type(ks) in [long, int]:
                        k = ks
                    else:
                        k = parse_keysym(ks)
                    if k is not None:
                        keysyms.append(k)
                    else:
                        keysyms.append(NoSymbol)
                        if ks is not None:
                            missing_keysyms.append(str(ks))
            for j in range(0, keysyms_per_keycode):
                keysym = NoSymbol
                if keysyms and j<len(keysyms) and keysyms[j] is not None:
                    keysym = keysyms[j]
                ckeysyms[i*keysyms_per_keycode+j] = keysym
        if len(missing_keysyms)>0:
            log.info("could not find the following keysyms: %s", " ".join(set(missing_keysyms)))
        return XChangeKeyboardMapping(display, first_keycode, keysyms_per_keycode, ckeysyms, num_codes)==0
    finally:
        free(ckeysyms)

cdef KeysymToKeycodes(Display *display, KeySym keysym):
    cdef int i, j
    min_keycode, max_keycode = _get_minmax_keycodes(display)
    keycodes = []
    for i in range(min_keycode, max_keycode+1):
        for j in range(0,8):
            if XkbKeycodeToKeysym(display, <KeyCode> i, j//4, j%4) == keysym:
                keycodes.append(i)
                break
    return keycodes

cdef _get_raw_keycode_mappings(Display * display):
    """
        returns a dict: {keycode, [keysyms]}
        for all the keycodes
    """
    cdef int keysyms_per_keycode                    #@DuplicatedSignature
    cdef XModifierKeymap* keymap
    cdef KeySym * keyboard_map
    cdef KeySym keysym                              #@DuplicatedSignature
    cdef KeyCode keycode
    min_keycode,max_keycode = _get_minmax_keycodes(display)
    keyboard_map = XGetKeyboardMapping(display, min_keycode, max_keycode - min_keycode + 1, &keysyms_per_keycode)
    log("XGetKeyboardMapping keysyms_per_keycode=%s", keysyms_per_keycode)
    mappings = {}
    i = 0
    keycode = min_keycode
    while keycode<max_keycode:
        keysyms = []
        for keysym_index in range(0, keysyms_per_keycode):
            keysym = keyboard_map[i*keysyms_per_keycode + keysym_index]
            keysyms.append(keysym)
        mappings[keycode] = keysyms
        i += 1
        keycode += 1
    XFree(keyboard_map)
    return mappings

def get_keycode_mappings(display_source):
    """
    the mappings from _get_raw_keycode_mappings are in raw format
    (keysyms as numbers), so here we convert into names:
    """
    cdef Display * display                          #@DuplicatedSignature
    cdef KeySym keysym                              #@DuplicatedSignature
    display = get_xdisplay_for(display_source)
    raw_mappings = _get_raw_keycode_mappings(display)
    mappings = {}
    for keycode, keysyms in raw_mappings.items():
        keynames = []
        for keysym in keysyms:
            if keysym!=NoSymbol:
                keyname = XKeysymToString(keysym)
            else:
                keyname = ""
            keynames.append(keyname)
        #now remove trailing empty entries:
        while len(keynames)>0 and keynames[-1]=="":
            keynames = keynames[:-1]
        if len(keynames)>0:
            mappings[keycode] = keynames
    return mappings


def get_keycodes(display_source, keyname):
    codes = []
    keysym = _parse_keysym(keyname)
    if not keysym:
        return  codes
    cdef Display * display                          #@DuplicatedSignature
    display = get_xdisplay_for(display_source)
    return KeysymToKeycodes(display, keysym)

def parse_modifier(name):
    return {
            "shift": 0,
            "lock" : 1,
            "control" : 2,
            "ctrl" : 2,
            "mod1" : 3,
            "mod2" : 4,
            "mod3" : 5,
            "mod4" : 6,
            "mod5" : 7,
            }.get(name.lower(), -1)
def modifier_name(modifier_index):
    return {
            0 : "shift",
            1 : "lock",
            2 : "control",
            3 : "mod1",
            4 : "mod2",
            5 : "mod3",
            6 : "mod4",
            7 : "mod5",
            }.get(modifier_index)


cdef _get_raw_modifier_mappings(Display * display):
    """
        returns a dict: {modifier_index, [keycodes]}
        for all keycodes (see above for list)
    """
    cdef int keysyms_per_keycode                    #@DuplicatedSignature
    cdef XModifierKeymap* keymap                    #@DuplicatedSignature
    cdef KeySym * keyboard_map                      #@DuplicatedSignature
    cdef KeySym keysym                              #@DuplicatedSignature
    cdef KeyCode keycode                            #@DuplicatedSignature
    min_keycode,max_keycode = _get_minmax_keycodes(display)
    keyboard_map = XGetKeyboardMapping(display, min_keycode, max_keycode - min_keycode + 1, &keysyms_per_keycode)
    mappings = {}
    i = 0
    keymap = get_keymap(display, False)
    assert keymap==NULL
    keymap = get_keymap(display, True)
    modifiermap = <KeyCode*> keymap.modifiermap
    for modifier in range(0, 8):
        keycodes = []
        k = 0
        while k<keymap.max_keypermod:
            keycode = modifiermap[i]
            if keycode!=NoSymbol:
                keycodes.append(keycode)
            k += 1
            i += 1
        mappings[modifier] = keycodes
    XFreeModifiermap(keymap)
    set_keymap(NULL)
    XFree(keyboard_map)
    return (keysyms_per_keycode, mappings)

cdef _get_modifier_mappings(Display * display):
    """
    the mappings from _get_raw_modifier_mappings are in raw format
    (index and keycode), so here we convert into names:
    """
    cdef KeySym keysym                      #@DuplicatedSignature
    keysyms_per_keycode, raw_mappings = _get_raw_modifier_mappings(display)
    mappings = {}
    for mod, keycodes in raw_mappings.items():
        modifier = modifier_name(mod)
        if not modifier:
            log.error("cannot find name for modifier %s", mod)
            continue
        keynames = []
        for keycode in keycodes:
            keysym = 0
            index = 0
            while (keysym==0 and index<keysyms_per_keycode):
                keysym = XkbKeycodeToKeysym(display, keycode, index//4, index%4)
                index += 1
            if keysym==0:
                log.info("no keysym found for keycode %s", keycode)
                continue
            keyname = XKeysymToString(keysym)
            if keyname not in keynames:
                keynames.append((keycode, keyname))
        mappings[modifier] = keynames
    return mappings

def get_modifier_mappings():
    cdef Display * display                          #@DuplicatedSignature
    display = get_xdisplay_for(gtk.gdk.get_default_root_window())
    return _get_modifier_mappings(display)

cdef xmodmap_clearmodifier(Display * display, int modifier):
    cdef KeyCode* keycode
    cdef XModifierKeymap* keymap                    #@DuplicatedSignature
    keymap = get_keymap(display, True)
    keycode = <KeyCode*> keymap.modifiermap
    log("clear modifier: clearing all %s for modifier=%s", keymap.max_keypermod, modifier)
    for i in range(0, keymap.max_keypermod):
        keycode[modifier*keymap.max_keypermod+i] = 0

cdef xmodmap_addmodifier(Display * display, int modifier, keysyms):
    cdef XModifierKeymap* keymap                    #@DuplicatedSignature
    cdef KeyCode keycode                            #@DuplicatedSignature
    cdef KeySym keysym                              #@DuplicatedSignature
    keymap = get_keymap(display, True)
    success = True
    log("add modifier: modifier %s=%s", modifier, keysyms)
    for keysym_str in keysyms:
        keysym = XStringToKeysym(keysym_str)
        log("add modifier: keysym(%s)=%s", keysym_str, keysym)
        keycodes = KeysymToKeycodes(display, keysym)
        log("add modifier: keycodes(%s)=%s", keysym, keycodes)
        if len(keycodes)==0:
            log.error("xmodmap_exec_add: no keycodes found for keysym %s/%s", keysym_str, keysym)
            success = False
        else:
            for k in keycodes:
                if k!=0:
                    keycode = k
                    keymap = XInsertModifiermapEntry(keymap, keycode, modifier)
                    if keymap!=NULL:
                        set_keymap(keymap)
                        log("add modifier: added keycode=%s for modifier %s and keysym=%s", k, modifier, keysym_str)
                    else:
                        log.error("add modifier: failed keycode=%s for modifier %s and keysym=%s", k, modifier, keysym_str)
                        success = False
                else:
                    log.info("add modifier: failed, found zero keycode for %s", modifier)
                    success = False
    return success


cdef _get_keycodes_down(Display * display):
    cdef char[32] keymap
    masktable = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80]
    down = []
    XQueryKeymap(display, keymap)
    for i in range(0, 256):
        if keymap[i >> 3] & masktable[i & 7]:
            down.append(i)
    return down

def get_keycodes_down(display_source):
    cdef Display * display                          #@DuplicatedSignature
    cdef char* key
    display = get_xdisplay_for(display_source)
    keycodes = _get_keycodes_down(display)
    keys = {}
    for keycode in keycodes:
        keysym = XkbKeycodeToKeysym(display, keycode, 0, 0)
        key = XKeysymToString(keysym)
        keys[keycode] = str(key)
    return keys

def unpress_all_keys(display_source):
    cdef Display * display                          #@DuplicatedSignature
    display = get_xdisplay_for(display_source)
    keycodes = _get_keycodes_down(display)
    for keycode in keycodes:
        xtest_fake_key(display_source, keycode, False)

cdef native_xmodmap(display_source, instructions):
    cdef Display * display                          #@DuplicatedSignature
    cdef XModifierKeymap* keymap                    #@DuplicatedSignature
    cdef int modifier
    set_keymap(NULL)
    display = get_xdisplay_for(display_source)
    unhandled = []
    map = None
    keycodes = {}
    new_keysyms = []
    try:
        for line in instructions:
            log("processing: %s", line)
            if not line:
                continue
            cmd = line[0]
            if cmd=="keycode":
                #line = ("keycode", keycode, [keysyms])
                keycode = int(line[1])
                keysyms = line[2]
                if keycode==0:
                    #keycode=0 means "any", ie: 'keycode any = Shift_L'
                    assert len(keysyms)==1
                    new_keysyms.append(keysyms[0])
                    continue
                elif keycode>0:
                    keycodes[keycode] = keysyms
                    continue
            elif cmd=="clear":
                #ie: ("clear", 1)
                modifier = line[1]
                if modifier>=0:
                    xmodmap_clearmodifier(display, modifier)
                    continue
            elif cmd=="add":
                #ie: ("add", "Control", ["Control_L", "Control_R"])
                modifier = line[1]
                keysyms = line[2]
                if modifier>=0:
                    if xmodmap_addmodifier(display, modifier, keysyms):
                        continue
            log.error("native_xmodmap could not handle instruction: %s", line)
            unhandled.append(line)
        if len(keycodes)>0:
            log("calling xmodmap_setkeycodes with %s", keycodes)
            xmodmap_setkeycodes(display, keycodes, new_keysyms)
    finally:
        keymap = get_keymap(display, False)
        if keymap!=NULL:
            set_keymap(NULL)
            log("saving modified keymap")
            if XSetModifierMapping(display, keymap)==MappingBusy:
                log.error("cannot change keymap: mapping busy: %s" % get_keycodes_down(display_source))
                unhandled = instructions
            XFreeModifiermap(keymap)
    log.debug("modify keymap: %s instructions, %s unprocessed", len(instructions), len(unhandled))
    return unhandled

def set_xmodmap(display_source, xmodmap_data):
    return native_xmodmap(display_source, xmodmap_data)

def grab_key(pywindow, keycode, modifiers):
    XGrabKey(get_xdisplay_for(pywindow), keycode, modifiers,
             get_xwindow(pywindow),
             # Really, grab the key even if it's also in another window we own
             False,
             # Don't stall the pointer upon this key being pressed:
             GrabModeAsync,
             # Don't stall the keyboard upon this key being pressed (need to
             # change this if we ever want to allow for multi-key bindings
             # a la emacs):
             GrabModeAsync)

def ungrab_all_keys(pywindow):
    XUngrabKey(get_xdisplay_for(pywindow), AnyKey, AnyModifier,
               get_xwindow(pywindow))

###################################
# XKillClient
###################################

def XKillClient(pywindow):
    cXKillClient(get_xdisplay_for(pywindow), get_xwindow(pywindow))

###################################
# XUnmapWindow
###################################

def unmap_with_serial(pywindow):
    serial = NextRequest(get_xdisplay_for(pywindow))
    XUnmapWindow(get_xdisplay_for(pywindow), get_xwindow(pywindow))
    return serial

###################################
# XTest
###################################

cdef extern from "X11/extensions/XTest.h":
    Bool XTestQueryExtension(Display *, int *, int *,
                             int * major, int * minor)
    int XTestFakeKeyEvent(Display *, unsigned int keycode,
                          Bool is_press, unsigned long delay)
    int XTestFakeButtonEvent(Display *, unsigned int button,
                             Bool is_press, unsigned long delay)

def _ensure_XTest_support(display_source):
    display = get_display_for(display_source)
    cdef int ignored = 0
    if display.get_data("XTest-support") is None:
        display.set_data("XTest-support",
                         XTestQueryExtension(get_xdisplay_for(display),
                                             &ignored, &ignored,
                                             &ignored, &ignored))
    if not display.get_data("XTest-support"):
        raise ValueError, "XTest not supported"

def xtest_fake_key(display_source, keycode, is_press):
    _ensure_XTest_support(display_source)
    XTestFakeKeyEvent(get_xdisplay_for(display_source), keycode, is_press, 0)

def xtest_fake_button(display_source, button, is_press):
    _ensure_XTest_support(display_source)
    XTestFakeButtonEvent(get_xdisplay_for(display_source), button, is_press, 0)

###################################
# Extension testing
###################################

# X extensions all have different APIs for negotiating their
# availability/version number, but a number of the more recent ones are
# similar enough to share code (in particular, Composite and DAMAGE, and
# probably also Xfixes, Xrandr, etc.).  (But note that we don't actually have
# to query for Xfixes support because 1) any server that can handle us at all
# already has a sufficiently advanced version of Xfixes, and 2) GTK+ already
# enables Xfixes for us automatically.)

cdef _ensure_extension_support(display_source, major, minor, extension,
                               Bool (*query_extension)(Display*, int*, int*),
                               Status (*query_version)(Display*, int*, int*)):
    cdef int event_base = 0, ignored = 0, cmajor = 0, cminor = 0
    display = get_display_for(display_source)
    key = extension + "-support"
    event_key = extension + "-event-base"
    if display.get_data(key) is None:
        # Haven't checked for this extension before
        display.set_data(key, False)
        if (query_extension)(get_xdisplay_for(display),
                              &event_base, &ignored):
            display.set_data(event_key, event_base)
            cmajor = major
            cminor = minor
            if (query_version)(get_xdisplay_for(display), &cmajor, &cminor):
                # See X.org bug #14511:
                log("found X11 extension %s with version %s.%s", extension, major, minor)
                if major == cmajor and minor <= cminor:
                    display.set_data(key, True)
                else:
                    raise ValueError("%s v%s.%s not supported; required: v%s.%s"
                                     % (extension, cmajor, cminor, major, minor))
        else:
            raise ValueError("X server does not support required extension %s"
                             % extension)
    if not display.get_data(key):
        raise ValueError, "insufficient %s support in server" % extension

###################################
# Composite
###################################

cdef extern from "X11/extensions/Xcomposite.h":
    Bool XCompositeQueryExtension(Display *, int *, int *)
    Status XCompositeQueryVersion(Display *, int * major, int * minor)
    unsigned int CompositeRedirectManual
    unsigned int CompositeRedirectAutomatic
    void XCompositeRedirectWindow(Display *, Window, int mode)
    void XCompositeRedirectSubwindows(Display *, Window, int mode)
    void XCompositeUnredirectWindow(Display *, Window, int mode)
    void XCompositeUnredirectSubwindows(Display *, Window, int mode)
    Pixmap XCompositeNameWindowPixmap(Display *, Window)

    int XFreePixmap(Display *, Pixmap)



def _ensure_XComposite_support(display_source):
    # We need NameWindowPixmap, but we don't need the overlay window
    # (v0.3) or the special manual-redirect clipping semantics (v0.4).
    _ensure_extension_support(display_source, 0, 2, "Composite",
                              XCompositeQueryExtension,
                              XCompositeQueryVersion)

def displayHasXComposite(display_source):
    try:
        _ensure_XComposite_support(display_source)
        return  True
    except Exception, e:
        log.error("%s", e)
    return False

def xcomposite_redirect_window(window):
    _ensure_XComposite_support(window)
    XCompositeRedirectWindow(get_xdisplay_for(window), get_xwindow(window),
                             CompositeRedirectManual)

def xcomposite_redirect_subwindows(window):
    _ensure_XComposite_support(window)
    XCompositeRedirectSubwindows(get_xdisplay_for(window), get_xwindow(window),
                                 CompositeRedirectManual)

def xcomposite_unredirect_window(window):
    _ensure_XComposite_support(window)
    XCompositeUnredirectWindow(get_xdisplay_for(window), get_xwindow(window),
                               CompositeRedirectManual)

def xcomposite_unredirect_subwindows(window):
    _ensure_XComposite_support(window)
    XCompositeUnredirectSubwindows(get_xdisplay_for(window), get_xwindow(window),
                                   CompositeRedirectManual)

class _PixmapCleanupHandler(object):
    "Reference count a GdkPixmap that needs explicit cleanup."
    def __init__(self, pixmap):
        self.pixmap = pixmap

    def __del__(self):
        if self.pixmap is not None:
            XFreePixmap(get_xdisplay_for(self.pixmap), self.pixmap.xid)
            self.pixmap = None

def xcomposite_name_window_pixmap(window):
    _ensure_XComposite_support(window)
    xpixmap = XCompositeNameWindowPixmap(get_xdisplay_for(window),
                                         get_xwindow(window))
    gpixmap = gtk.gdk.pixmap_foreign_new_for_display(get_display_for(window),
                                                     xpixmap)
    if gpixmap is None:
        # Can't always actually get a pixmap, e.g. if window is not yet mapped
        # or if it has disappeared.  In such cases we might not actually see
        # an X error yet, but xpixmap will actually point to an invalid
        # Pixmap, and pixmap_foreign_new_for_display will fail when it tries
        # to look up that pixmap's dimensions, and return None.
        return None
    else:
        gpixmap.set_colormap(window.get_colormap())
        return _PixmapCleanupHandler(gpixmap)

###################################
# Randr
###################################

cdef extern from "X11/extensions/randr.h":
    cdef unsigned int RR_Rotate_0

cdef extern from "X11/extensions/Xrandr.h":
    Bool XRRQueryExtension(Display *, int *, int *)
    Status XRRQueryVersion(Display *, int * major, int * minor)
    ctypedef struct XRRScreenSize:
        int width, height
        int mwidth, mheight
    XRRScreenSize *XRRSizes(Display *dpy, int screen, int *nsizes)
    void XRRSetScreenSize(Display *dpy, Window w, int width, int height, int mmWidth, int mmHeight)

    ctypedef unsigned short SizeID
    ctypedef struct XRRScreenConfiguration:
        pass
    ctypedef unsigned short Rotation
    Status XRRSetScreenConfigAndRate(Display *dpy, XRRScreenConfiguration *config,
                                  Drawable draw, int size_index, Rotation rotation,
                                  short rate, Time timestamp)
    XRRScreenConfiguration *XRRGetScreenInfo(Display *, Window w)
    XRRScreenSize *XRRConfigSizes(XRRScreenConfiguration *config, int *nsizes)
    short *XRRConfigRates(XRRScreenConfiguration *config, int sizeID, int *nrates)
    SizeID XRRConfigCurrentConfiguration(XRRScreenConfiguration *config, Rotation *rotation)

    void XRRFreeScreenConfigInfo(XRRScreenConfiguration *)

def has_randr():
    try:
        _ensure_extension_support(gtk.gdk.get_default_root_window(), 1, 2, "Randr",
                                 XRRQueryExtension,
                                 XRRQueryVersion)
        return True
    except Exception, e:
        log.warn("Warning: %s", e)
        return False

cdef _get_screen_sizes(display_source):
    cdef Display * display                          #@DuplicatedSignature
    display = get_xdisplay_for(display_source)
    cdef int num_sizes = 0
    cdef XRRScreenSize * xrrs
    cdef XRRScreenSize xrr
    xrrs = XRRSizes(display, 0, &num_sizes)
    sizes = []
    for i in range(num_sizes):
        xrr = xrrs[i]
        sizes.append((xrr.width, xrr.height))
    return    sizes

def get_screen_sizes():
    return _get_screen_sizes(gtk.gdk.display_get_default())

cdef _set_screen_size(display_source, pywindow, width, height):
    cdef Display * display                          #@DuplicatedSignature
    cdef Window window
    cdef XRRScreenConfiguration *config
    cdef int num_sizes = 0                          #@DuplicatedSignature
    cdef int num_rates = 0
    cdef short* rates = <short*> 0
    cdef short rate = 0
    cdef Rotation rotation = 0
    cdef Time time = 0
    cdef int sizeID = 0
    cdef XRRScreenSize *xrrs
    cdef XRRScreenSize xrr                          #@DuplicatedSignature

    display = get_xdisplay_for(display_source)
    window = get_xwindow(pywindow)
    try:
        config = XRRGetScreenInfo(display, window)
        xrrs = XRRConfigSizes(config, &num_sizes)
        sizes = []
        sizeID = -1
        for i in range(num_sizes):
            xrr = xrrs[i]
            if xrr.width==width and xrr.height==height:
                sizeID = i
        if sizeID<0:
            log.error("size not found for %sx%s" % (width, height))
            return False
        rates = XRRConfigRates(config, sizeID, &num_rates)
        rate = rates[0]
        rotation = RR_Rotate_0
        time = CurrentTime    #gtk.gdk.x11_get_server_time(pywindow)
        status = XRRSetScreenConfigAndRate(display, config, window, sizeID, rotation, rate, time)
        if status != Success:
            log.error("failed to set new screen size")
            return False
        return True
    finally:
        XRRFreeScreenConfigInfo(config)

def get_screen_size():
    return _get_screen_size(gtk.gdk.get_default_root_window())

def _get_screen_size(pywindow):
    cdef Display * display                          #@DuplicatedSignature
    cdef Window window                              #@DuplicatedSignature
    cdef XRRScreenSize *xrrs                        #@DuplicatedSignature
    cdef Rotation original_rotation
    cdef int num_sizes = 0                          #@DuplicatedSignature
    cdef SizeID size_id
    display = get_xdisplay_for(pywindow)
    window = get_xwindow(pywindow)
    cdef XRRScreenConfiguration *config             #@DuplicatedSignature
    try:
        config = XRRGetScreenInfo(display, window)
        xrrs = XRRConfigSizes(config, &num_sizes)
        #short original_rate = XRRConfigCurrentRate(config);
        size_id = XRRConfigCurrentConfiguration(config, &original_rotation);

        width = xrrs[size_id].width;
        height = xrrs[size_id].height;
        return int(width), int(height)
    finally:
        XRRFreeScreenConfigInfo(config)

def set_screen_size(width, height):
    display = gtk.gdk.display_get_default()
    root_window = gtk.gdk.get_default_root_window()
    return _set_screen_size(display, root_window, width, height)

###################################
# XKB bell
###################################
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

cdef extern from "X11/XKBlib.h":
    KeySym XkbKeycodeToKeysym(Display *display, KeyCode kc, int group, int level)
    Bool XkbQueryExtension(Display *, int *opcodeReturn, int *eventBaseReturn, int *errorBaseReturn, int *majorRtrn, int *minorRtrn)
    Bool XkbSelectEvents(Display *, unsigned int deviceID, unsigned int affect, unsigned int values)
    Bool XkbDeviceBell(Display *, Window w, int deviceSpec, int bellClass, int bellID, int percent, Atom name)
    Bool XkbSetAutoRepeatRate(Display *, unsigned int deviceSpec, unsigned int delay, unsigned int interval)
    Bool XkbGetAutoRepeatRate(Display *, unsigned int deviceSpec, unsigned int *delayRtrn, unsigned int *intervalRtrn)

def get_key_repeat_rate():
    cdef Display * display                          #@DuplicatedSignature
    cdef unsigned int deviceSpec = XkbUseCoreKbd
    cdef unsigned int delay = 0
    cdef unsigned int interval = 0
    display = get_xdisplay_for(gtk.gdk.get_default_root_window())
    if not XkbGetAutoRepeatRate(display, deviceSpec, &delay, &interval):
        return None
    return (delay, interval)

def set_key_repeat_rate(delay, interval):
    cdef Display * display                          #@DuplicatedSignature
    cdef unsigned int deviceSpec = XkbUseCoreKbd    #@DuplicatedSignature
    cdef unsigned int cdelay = delay
    cdef unsigned int cinterval = interval
    display = get_xdisplay_for(gtk.gdk.get_default_root_window())
    return XkbSetAutoRepeatRate(display, deviceSpec, cdelay, cinterval)

def get_XKB_event_base():
    cdef int opcode = 0
    cdef int event_base = 0
    cdef int error_base = 0
    cdef int major = 0
    cdef int minor = 0
    cdef Display * display                          #@DuplicatedSignature
    display = get_xdisplay_for(gtk.gdk.get_default_root_window())
    XkbQueryExtension(display, &opcode, &event_base, &error_base, &major, &minor)
    return int(event_base)

def selectBellNotification(pywindow, on):
    cdef Display * display                          #@DuplicatedSignature
    cdef int bits = XkbBellNotifyMask
    display = get_xdisplay_for(pywindow)
    if not on:
        bits = 0
    XkbSelectEvents(display, XkbUseCoreKbd, XkbBellNotifyMask, bits)

def device_bell(pywindow, deviceSpec, bellClass, bellID, percent, name):
    cdef Display * display                          #@DuplicatedSignature
    cdef Window window                              #@DuplicatedSignature
    display = get_xdisplay_for(pywindow)
    window = get_xwindow(pywindow)
    name_atom = get_xatom(name)
    return XkbDeviceBell(display, window, deviceSpec, bellClass, bellID,  percent, name_atom)


###################################
# Xfixes: cursor events
###################################
cdef extern from "X11/extensions/xfixeswire.h":
    unsigned int XFixesCursorNotify
    unsigned long XFixesDisplayCursorNotifyMask
    void XFixesSelectCursorInput(Display *, Window w, long mask)

cdef extern from "X11/extensions/Xfixes.h":
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
        #XFixes v2:
        #char* name
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

    Bool XFixesQueryExtension(Display *, int *event_base, int *error_base)
    XFixesCursorImage* XFixesGetCursorImage(Display *)

    ctypedef XID XserverRegion
    XserverRegion XFixesCreateRegion(Display *, XRectangle *, int nrectangles)
    void XFixesDestroyRegion(Display *, XserverRegion)

cdef argbdata_to_pixdata(unsigned long* data, len):
    if len <= 0:
        return None
    import array
    # Create byte array
    b = array.array('b', '\0'* len*4)
    offset = 0
    i = 0
    offset = 0
    while i < len:
        argb = data[i] & 0xffffffff
        rgba = (argb << 8) | (argb >> 24)
        b1 = (rgba >> 24)  & 0xff
        b2 = (rgba >> 16) & 0xff
        b3 = (rgba >> 8) & 0xff
        b4 = rgba & 0xff
        # Ref: http://docs.python.org/dev/3.0/library/struct.html
        struct.pack_into("=BBBB", b, offset, b1, b2, b3, b4)
        offset = offset + 4
        i = i + 1
    return b

def get_cursor_image():
    cdef Display * display                              #@DuplicatedSignature
    cdef XFixesCursorImage* image
    #cdef char* pixels
    display = get_xdisplay_for(gtk.gdk.get_default_root_window())
    try:
        image = XFixesGetCursorImage(display)
        if image==NULL:
            return  None
        l = image.width*image.height
        pixels = argbdata_to_pixdata(image.pixels, l)
        return [image.x, image.y, image.width, image.height, image.xhot, image.yhot,
            image.cursor_serial, pixels]
    finally:
        XFree(image)

def get_XFixes_event_base():
    cdef int event_base = 0                             #@DuplicatedSignature
    cdef int error_base = 0                             #@DuplicatedSignature
    cdef Display * display                              #@DuplicatedSignature
    display = get_xdisplay_for(gtk.gdk.get_default_root_window())
    XFixesQueryExtension(display, &event_base, &error_base)
    return int(event_base)

def selectCursorChange(pywindow, on):
    cdef Display * display                              #@DuplicatedSignature
    display = get_xdisplay_for(pywindow)
    cdef Window window                                  #@DuplicatedSignature
    window = get_xwindow(pywindow)
    if on:
        v = XFixesDisplayCursorNotifyMask
    else:
        v = 0
    XFixesSelectCursorInput(display, window, v)


###################################
# Xdamage
###################################


cdef extern from "X11/extensions/Xdamage.h":
    ctypedef XID Damage
    unsigned int XDamageReportDeltaRectangles
    #unsigned int XDamageReportRawRectangles
    unsigned int XDamageNotify
    ctypedef struct XDamageNotifyEvent:
        Damage damage
        int level
        Bool more
        XRectangle area
    Bool XDamageQueryExtension(Display *, int * event_base, int *)
    Status XDamageQueryVersion(Display *, int * major, int * minor)
    Damage XDamageCreate(Display *, Drawable, int level)
    void XDamageDestroy(Display *, Damage)
    void XDamageSubtract(Display *, Damage,
                         XserverRegion repair, XserverRegion parts)

def _ensure_XDamage_support(display_source):
    _ensure_extension_support(display_source, 1, 0, "DAMAGE",
                              XDamageQueryExtension,
                              XDamageQueryVersion)

def xdamage_start(window):
    _ensure_XDamage_support(window)
    return XDamageCreate(get_xdisplay_for(window), get_xwindow(window),
                         XDamageReportDeltaRectangles)

def xdamage_stop(display_source, handle):
    _ensure_XDamage_support(display_source)
    XDamageDestroy(get_xdisplay_for(display_source), handle)

def xdamage_acknowledge(display_source, handle):
    # def xdamage_acknowledge(display_source, handle, x, y, width, height):
    # cdef XRectangle rect
    # rect.x = x
    # rect.y = y
    # rect.width = width
    # rect.height = height
    # repair = XFixesCreateRegion(get_xdisplay_for(display_source), &rect, 1)
    # XDamageSubtract(get_xdisplay_for(display_source), handle, repair, XNone)
    # XFixesDestroyRegion(get_xdisplay_for(display_source), repair)

    # DeltaRectangles mode + XDamageSubtract is broken, because repair
    # operations trigger a flood of re-reported events (see freedesktop.org bug
    # #14648 for details).  So instead we always repair all damage.  This
    # means we may get redundant damage notifications if areas outside of the
    # rectangle we actually repaired get re-damaged, but it avoids the
    # quadratic blow-up that fixing just the correct area causes, and still
    # reduces the number of events we receive as compared to just using
    # RawRectangles mode.  This is very important for things like, say,
    # drawing a scatterplot in R, which may make hundreds of thousands of
    # draws to the same location, and with RawRectangles mode xpra can lag by
    # seconds just trying to keep track of the damage.
    XDamageSubtract(get_xdisplay_for(display_source), handle, XNone, XNone)

###################################
# Smarter convenience wrappers
###################################

def myGetSelectionOwner(display_source, pyatom):
    return XGetSelectionOwner(get_xdisplay_for(display_source),
                              get_xatom(pyatom))

cdef long cast_to_long(i):
    if i < 0:
        return <long>i
    else:
        return <long><unsigned long>i

def sendClientMessage(target, propagate, event_mask,
                      message_type, data0, data1, data2, data3, data4):
    # data0 etc. are passed through get_xatom, so they can be integers, which
    # are passed through directly, or else they can be strings, which are
    # converted appropriately.
    cdef Display * display                              #@DuplicatedSignature
    display = get_xdisplay_for(target)
    cdef Window w
    w = get_xwindow(target)
    log("sending message to %s", hex(w))
    cdef XEvent e
    e.type = ClientMessage
    e.xany.display = display
    e.xany.window = w
    e.xclient.message_type = get_xatom(message_type)
    e.xclient.format = 32
    e.xclient.data.l[0] = cast_to_long(get_xatom(data0))
    e.xclient.data.l[1] = cast_to_long(get_xatom(data1))
    e.xclient.data.l[2] = cast_to_long(get_xatom(data2))
    e.xclient.data.l[3] = cast_to_long(get_xatom(data3))
    e.xclient.data.l[4] = cast_to_long(get_xatom(data4))
    cdef Status s
    s = XSendEvent(display, w, propagate, event_mask, &e)
    if s == 0:
        raise ValueError, "failed to serialize ClientMessage"

def sendConfigureNotify(pywindow):
    cdef Display * display              #@DuplicatedSignature
    display = get_xdisplay_for(pywindow)
    cdef Window window                  #@DuplicatedSignature
    window = get_xwindow(pywindow)

    # Get basic attributes
    cdef XWindowAttributes attrs        #@DuplicatedSignature
    XGetWindowAttributes(display, window, &attrs)

    # Figure out where the window actually is in root coordinate space
    cdef int dest_x = 0, dest_y = 0
    cdef Window child = 0
    if not XTranslateCoordinates(display, window,
                                 get_xwindow(gtk.gdk.get_default_root_window()),
                                 0, 0,
                                 &dest_x, &dest_y, &child):
        # Window seems to have disappeared, so never mind.
        log("couldn't TranslateCoordinates (maybe window is gone)")
        return

    # Send synthetic ConfigureNotify (ICCCM 4.2.3, for example)
    cdef XEvent e                       #@DuplicatedSignature
    e.type = ConfigureNotify
    e.xconfigure.event = window
    e.xconfigure.window = window
    e.xconfigure.x = dest_x
    e.xconfigure.y = dest_y
    e.xconfigure.width = attrs.width
    e.xconfigure.height = attrs.height
    e.xconfigure.border_width = attrs.border_width
    e.xconfigure.above = XNone
    e.xconfigure.override_redirect = attrs.override_redirect

    cdef Status s                       #@DuplicatedSignature
    s = XSendEvent(display, window, False, StructureNotifyMask, &e)
    if s == 0:
        raise ValueError, "failed to serialize ConfigureNotify"

def configureAndNotify(pywindow, x, y, width, height, fields=None):
    cdef Display * display              #@DuplicatedSignature
    display = get_xdisplay_for(pywindow)
    cdef Window window                  #@DuplicatedSignature
    window = get_xwindow(pywindow)

    # Reconfigure the window.  We have to use XConfigureWindow directly
    # instead of GdkWindow.resize, because GDK does not give us any way to
    # squash the border.

    # The caller can pass an XConfigureWindow-style fields mask to turn off
    # some of these bits; this is useful if they are pulling such a field out
    # of a ConfigureRequest (along with the other arguments they are passing
    # to us).  This also means we need to be careful to zero out any bits
    # besides these, because they could be set to anything.
    all_optional_fields_we_know = CWX | CWY | CWWidth | CWHeight
    if fields is None:
        fields = all_optional_fields_we_know
    else:
        fields = fields & all_optional_fields_we_know
    # But we always unconditionally squash the border to zero.
    fields = fields | CWBorderWidth

    cdef XWindowChanges changes
    changes.x = x
    changes.y = y
    changes.width = width
    changes.height = height
    changes.border_width = 0
    cXConfigureWindow(display, window, fields, &changes)
    # Tell the client.
    sendConfigureNotify(pywindow)

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
# Our hooks in any case use the "wimpiggy-route-events-to" GObject user data
# field of the gtk.gdk.Window's involved.  For the SubstructureRedirect
# events, we use this field of either the window that is making the request,
# or, if its field is unset, to the window that actually has
# SubstructureRedirect selected on it; for other events, we send it to the
# event window directly.
#
# So basically, to use this code:
#   -- Import this module to install the global event filters
#   -- Call win.set_data("wimpiggy-route-events-to", obj) on random windows.
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

def addXSelectInput(pywindow, add_mask):
    cdef XWindowAttributes curr
    XGetWindowAttributes(get_xdisplay_for(pywindow),
                         get_xwindow(pywindow),
                         &curr)
    mask = curr.your_event_mask
    mask = mask | add_mask
    XSelectInput(get_xdisplay_for(pywindow),
                 get_xwindow(pywindow),
                 mask)

def substructureRedirect(pywindow):
    """Enable SubstructureRedirect on the given window.

    This enables reception of MapRequest and ConfigureRequest events.  At the
    X level, it also enables the reception of CirculateRequest events, but
    those are pretty useless, so we just ignore such events unconditionally
    rather than routing them anywhere.  (The circulate request appears to be
    in the protocol just so simple window managers have an easy way to
    implement the equivalent of alt-tab; I can't imagine how it'd be useful
    these days.  Metacity and KWin do not support it; GTK+/GDK and Qt4 provide
    no way to actually send it.)"""
    addXSelectInput(pywindow, SubstructureRedirectMask)

def selectFocusChange(pywindow):
    addXSelectInput(pywindow, FocusChangeMask)

# No need to select for ClientMessage; in fact, one cannot select for
# ClientMessages.  If they are sent with an empty mask, then they go to the
# client that owns the window they are sent to, otherwise they go to any
# clients that are selecting for that mask they are sent with.

_ev_receiver_key = "wimpiggy-route-events-to"
def add_event_receiver(window, receiver):
    receivers = window.get_data(_ev_receiver_key)
    if receivers is None:
        receivers = set()
        window.set_data(_ev_receiver_key, receivers)
    if receiver not in receivers:
        receivers.add(receiver)

def remove_event_receiver(window, receiver):
    receivers = window.get_data(_ev_receiver_key)
    if receivers is None:
        return
    receivers.discard(receiver)
    if not receivers:
        receivers = None
        window.set_data(_ev_receiver_key, receivers)

def _maybe_send_event(window, signal, event):
    handlers = window.get_data(_ev_receiver_key)
    if handlers is not None:
        # Copy the 'handlers' list, because signal handlers might cause items
        # to be added or removed from it while we are iterating:
        for handler in list(handlers):
            if signal in gobject.signal_list_names(handler):
                log("  forwarding event to a %s handler's %s signal",
                    type(handler).__name__, signal)
                handler.emit(signal, event)
                log("  forwarded")
            else:
                log("  not forwarding to %s handler, it has no %s signal",
                    type(handler).__name__, signal)
    else:
        log("  no handler registered for this window, ignoring event")

def _route_event(event, signal, parent_signal):
    # Sometimes we get GDK events with event.window == None, because they are
    # for windows we have never created a GdkWindow object for, and GDK
    # doesn't do so just for this event.  As far as I can tell this only
    # matters for override redirect windows when they disappear, and we don't
    # care about those anyway.
    if event.window is None:
        log("  event.window is None, ignoring")
        assert event.type in (gtk.gdk.UNMAP, gtk.gdk.DESTROY)
        return
    if event.window is event.delivered_to:
        if signal is not None:
            log("  event was delivered to window itself")
            _maybe_send_event(event.window, signal, event)
        else:
            log("  received event on window itself but have no signal for that")
    else:
        if parent_signal is not None:
            log("  event was delivered to parent window")
            _maybe_send_event(event.delivered_to, parent_signal, event)
        else:
            log("  received event on a parent window but have no parent signal")

CursorNotify = 0
XKBNotify = 0
_x_event_signals = {}
def init_x11_events():
    global _x_event_signals, XKBNotify, CursorNotify
    XKBNotify = get_XKB_event_base()
    CursorNotify = XFixesCursorNotify+get_XFixes_event_base()
    _x_event_signals = {
        MapRequest: (None, "child-map-request-event"),
        ConfigureRequest: (None, "child-configure-request-event"),
        FocusIn: ("wimpiggy-focus-in-event", None),
        FocusOut: ("wimpiggy-focus-out-event", None),
        ClientMessage: ("wimpiggy-client-message-event", None),
        MapNotify: ("wimpiggy-map-event", "wimpiggy-child-map-event"),
        UnmapNotify: ("wimpiggy-unmap-event", "wimpiggy-child-unmap-event"),
        DestroyNotify: ("wimpiggy-destroy-event", None),
        ConfigureNotify: ("wimpiggy-configure-event", None),
        ReparentNotify: ("wimpiggy-reparent-event", None),
        PropertyNotify: ("wimpiggy-property-notify-event", None),
        KeyPress: ("wimpiggy-key-press-event", None),
        CursorNotify: ("wimpiggy-cursor-event", None),
        XKBNotify: ("wimpiggy-xkb-event", None),
        "XDamageNotify": ("wimpiggy-damage-event", None),
        }

def _gw(display, xwin):
    return trap.call_synced(get_pywindow, display, xwin)

cdef GdkFilterReturn x_event_filter(GdkXEvent * e_gdk,
                                    GdkEvent * gdk_event,
                                    void * userdata) with gil:
    cdef XEvent * e
    cdef XDamageNotifyEvent * damage_e
    cdef XFixesCursorNotifyEvent * cursor_e
    cdef XkbAnyEvent * xkb_e
    cdef XkbBellNotifyEvent * bell_e
    e = <XEvent*>e_gdk
    if e.xany.send_event and e.type not in (ClientMessage, UnmapNotify):
        return GDK_FILTER_CONTINUE
    try:
        d = wrap(<cGObject*>gdk_x11_lookup_xdisplay(e.xany.display))
        my_events = dict(_x_event_signals)
        if d.get_data("DAMAGE-event-base") is not None:
            damage_type = d.get_data("DAMAGE-event-base") + XDamageNotify
            my_events[damage_type] = my_events["XDamageNotify"]
        else:
            damage_type = -1
        if e.type in my_events:
            log("x_event_filter event=%s", str(my_events.get(e.type)))
            pyev = AdHocStruct()
            pyev.type = e.type
            pyev.send_event = e.xany.send_event
            pyev.display = d
            # Unmarshal:
            try:
                if e.type != XKBNotify:
                    pyev.delivered_to = _gw(d, e.xany.window)
                if e.type == MapRequest:
                    log("MapRequest received")
                    pyev.window = _gw(d, e.xmaprequest.window)
                elif e.type == ConfigureRequest:
                    log("ConfigureRequest received")
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
                    pyev.detail = e.xconfigurerequest.detail
                    pyev.value_mask = e.xconfigurerequest.value_mask
                elif e.type in (FocusIn, FocusOut):
                    log("FocusIn/FocusOut received")
                    pyev.window = _gw(d, e.xfocus.window)
                    pyev.mode = e.xfocus.mode
                    pyev.detail = e.xfocus.detail
                elif e.type == ClientMessage:
                    log("ClientMessage received")
                    pyev.window = _gw(d, e.xany.window)
                    if long(e.xclient.message_type) > (long(2) ** 32):
                        log.warn("Xlib claims that this ClientEvent's 32-bit "
                                 + "message_type is %s.  "
                                 + "Note that this is >2^32.  "
                                 + "This makes no sense, so I'm ignoring it.",
                                 e.xclient.message_type)
                        return GDK_FILTER_CONTINUE
                    pyev.message_type = get_pyatom(pyev.display,
                                                   e.xclient.message_type)
                    pyev.format = e.xclient.format
                    # I am lazy.  Add this later if needed for some reason.
                    if pyev.format != 32:
                        log.warn("FIXME: Ignoring ClientMessage type=%s with format=%s (!=32)" % (pyev.message_type, pyev.format))
                        return GDK_FILTER_CONTINUE
                    pieces = []
                    for i in xrange(5):
                        # Mask with 0xffffffff to prevent sign-extension on
                        # architectures where Python's int is 64-bits.
                        pieces.append(int(e.xclient.data.l[i]) & 0xffffffff)
                    pyev.data = tuple(pieces)
                elif e.type == MapNotify:
                    log("MapNotify event received")
                    pyev.window = _gw(d, e.xmap.window)
                    pyev.override_redirect = e.xmap.override_redirect
                elif e.type == UnmapNotify:
                    log("UnmapNotify event received")
                    pyev.serial = e.xany.serial
                    pyev.window = _gw(d, e.xunmap.window)
                elif e.type == DestroyNotify:
                    log("DestroyNotify event received")
                    pyev.window = _gw(d, e.xdestroywindow.window)
                elif e.type == PropertyNotify:
                    log("PropertyNotify event received")
                    pyev.window = _gw(d, e.xany.window)
                    pyev.atom = trap.call_synced(get_pyatom, d,
                                                 e.xproperty.atom)
                elif e.type == ConfigureNotify:
                    log("ConfigureNotify event received")
                    pyev.window = _gw(d, e.xconfigure.window)
                    pyev.x = e.xconfigure.x
                    pyev.y = e.xconfigure.y
                    pyev.width = e.xconfigure.width
                    pyev.height = e.xconfigure.height
                    pyev.border_width = e.xconfigure.border_width
                elif e.type == ReparentNotify:
                    log("ReparentNotify event received")
                    pyev.window = _gw(d, e.xreparent.window)
                elif e.type == KeyPress:
                    log("KeyPress event received")
                    pyev.window = _gw(d, e.xany.window)
                    pyev.hardware_keycode = e.xkey.keycode
                    pyev.state = e.xkey.state
                elif e.type == CursorNotify:
                    log("Cursor event received")
                    pyev.window = _gw(d, e.xany.window)
                    cursor_e = <XFixesCursorNotifyEvent*>e
                    pyev.cursor_serial = cursor_e.cursor_serial
                elif e.type == XKBNotify:
                    # note we could just cast directly to XkbBellNotifyEvent
                    # but this would be dirty, and we may want to catch
                    # other types of XKB events in the future
                    xkb_e = <XkbAnyEvent*>e
                    log("XKB event received xkb_type=%s", xkb_e.xkb_type)
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
                        log("using bell_e.window=%s", bell_e.window)
                        pyev.window = _gw(d, bell_e.window)
                    else:
                        pyev.window = d.get_default_screen().get_root_window()
                        log("bell using root window=%s", pyev.window)
                    pyev.event_only = bool(bell_e.event_only)
                    pyev.delivered_to = pyev.window
                    pyev.window_model = None
                    pyev.bell_name = get_pyatom(pyev.window, bell_e.name)
                    log("XKB BellEvent: event=%r", pyev)
                elif e.type == damage_type:
                    log("DamageNotify received")
                    damage_e = <XDamageNotifyEvent*>e
                    pyev.window = _gw(d, e.xany.window)
                    pyev.damage = damage_e.damage
                    pyev.x = damage_e.area.x
                    pyev.y = damage_e.area.y
                    pyev.width = damage_e.area.width
                    pyev.height = damage_e.area.height
            except XError, e:
                log("Some window in our event disappeared before we could "
                    + "handle the event; so I'm just ignoring it instead.")
            else:
                # Dispatch:
                # The int() here forces a cast from a C integer to a Python
                # integer, to work around a bug in some versions of Pyrex:
                #   http://www.mail-archive.com/pygr-dev@googlegroups.com/msg00142.html
                #   http://lists.partiwm.org/pipermail/parti-discuss/2009-January/000071.html
                _route_event(pyev, *my_events[int(e.type)])
    except (KeyboardInterrupt, SystemExit):
        log("exiting on KeyboardInterrupt/SystemExit")
        gtk_main_quit_really()
    except:
        log.warn("Unhandled exception in x_event_filter:", exc_info=True)
    return GDK_FILTER_CONTINUE

def init_x11_filter():
    init_x11_events()
    gdk_window_add_filter(<cGdkWindow*>0, x_event_filter, <void*>0)
