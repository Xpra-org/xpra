# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time

import gobject
import gtk
import gtk.gdk

from xpra.util import dump_exc, AdHocStruct
from xpra.gtk_common.quit import gtk_main_quit_really
from xpra.x11.gtk_x11.error import trap, XError

from xpra.log import Logger
log = Logger("xpra.gtk_x11.gdk_bindings")

def noop(*args, **kwargs):
    pass
X11_DEBUG = os.environ.get("XPRA_X11_DEBUG", "0")!="0"
if X11_DEBUG or os.environ.get("XPRA_X11_LOG", "0")!="0":
    debug = log.debug
    info = log.info
else:
    debug = noop
    info = noop
warn = log.warn
error = log.error
XSHM_DEBUG = os.environ.get("XPRA_XSHM_DEBUG", "0")!="0"
if XSHM_DEBUG:
    xshm_debug = log.info
else:
    xshm_debug = noop


###################################
# Headers, python magic
###################################
cdef extern from "Python.h":
    ctypedef int Py_ssize_t
    ctypedef object PyObject
    ctypedef void** const_void_pp "const void**"
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

cdef extern from "stdlib.h":
    void* malloc(size_t __size)
    void free(void* mem)

cdef extern from "X11/Xutil.h":
    pass

cdef extern from "gdk/gdk.h":
    pass
cdef extern from "gdk/gdkx.h":
    pass

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
    object pygobject_new(cGObject * contents)

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
        XCirculateRequestEvent xcirculaterequest
        XConfigureEvent xconfigure
        XFocusChangeEvent xfocus
        XClientMessageEvent xclient
        XMapEvent xmap
        XUnmapEvent xunmap
        XReparentEvent xreparent
        XDestroyWindowEvent xdestroywindow
        XPropertyEvent xproperty

    Bool XQueryExtension(Display * display, char *name,
                         int *major_opcode_return, int *first_event_return, int *first_error_return)

    Status XQueryTree(Display * display, Window w,
                      Window * root, Window * parent,
                      Window ** children, unsigned int * nchildren)

    ctypedef char* XPointer

    ctypedef struct XImage:
        int width
        int height
        int xoffset             # number of pixels offset in X direction
        int format              # XYBitmap, XYPixmap, ZPixmap
        char *data              # pointer to image data
        int byte_order          # data byte order, LSBFirst, MSBFirst
        int bitmap_unit         # quant. of scanline 8, 16, 32
        int bitmap_bit_order    # LSBFirst, MSBFirst
        int bitmap_pad          # 8, 16, 32 either XY or ZPixmap
        int depth               # depth of image
        int bytes_per_line      # accelerator to next scanline
        int bits_per_pixel      # bits per pixel (ZPixmap)
        unsigned long red_mask  # bits in z arrangement
        unsigned long green_mask
        unsigned long blue_mask
        XPointer *obdata
        void *funcs

    unsigned long AllPlanes
    int XYPixmap
    int ZPixmap
    int MSBFirst
    int LSBFirst

    XImage *XGetImage(Display *display, Drawable d,
            int x, int y, unsigned int width, unsigned int  height,
            unsigned long plane_mask, int format)

    void XDestroyImage(XImage *ximage)

    Status XGetGeometry(Display *display, Drawable d, Window *root_return,
                        int *x_return, int *y_return, unsigned int  *width_return, unsigned int *height_return,
                        unsigned int *border_width_return, unsigned int *depth_return)

cdef extern from "X11/extensions/xfixeswire.h":
    unsigned int XFixesCursorNotify
    unsigned long XFixesDisplayCursorNotifyMask

cdef extern from "X11/extensions/Xdamage.h":
    ctypedef XID Damage
    unsigned int XDamageNotify
    ctypedef struct XDamageNotifyEvent:
        Damage damage
        int level
        Bool more
        XRectangle area
    Bool XDamageQueryExtension(Display *, int * event_base, int * error_base)

cdef extern from "X11/extensions/Xcomposite.h":
    Bool XCompositeQueryExtension(Display *, int *, int *)
    Status XCompositeQueryVersion(Display *, int * major, int * minor)
    int XFreePixmap(Display *, Pixmap)
    Pixmap XCompositeNameWindowPixmap(Display *, Window)

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

cdef extern from "X11/extensions/XShm.h":
    unsigned int ShmCompletion
    ctypedef struct ShmSeg:
        pass
    ctypedef struct XShmSegmentInfo:
        ShmSeg shmseg   # resource id
        int shmid       # kernel id
        char *shmaddr   # address in client
        Bool readOnly   # how the server should attach it

    XShmQueryExtension(Display *display)
    Bool XShmQueryVersion(Display *display, int *major, int *minor, Bool *pixmaps)

    Bool XShmAttach(Display *display, XShmSegmentInfo *shminfo)
    Bool XShmDetach(Display *display, XShmSegmentInfo *shminfo)

    XImage *XShmCreateImage(Display *display, Visual *visual,
                            unsigned int depth, int format, char *data,
                            XShmSegmentInfo *shminfo,
                            unsigned int width, unsigned int height)

    Bool XShmGetImage(Display *display, Drawable d, XImage *image,
                      int x, int y,
                      unsigned long plane_mask)

    int XShmGetEventBase(Display *display)


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

# Basic utilities:

def get_xwindow(pywindow):
    return GDK_WINDOW_XID(<cGdkWindow*>unwrap(pywindow, gtk.gdk.Window))

def get_pywindow(display_source, xwindow):
    if xwindow==0:
        return None
    disp = get_display_for(display_source)
    win = gtk.gdk.window_foreign_new_for_display(disp, xwindow)
    if win is None:
        debug("cannot get gdk window for %s : %s", display_source, xwindow)
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
        raise Exception("weirdly huge purported xatom: %s" % xatom)
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

class PropertyError(Exception):
    pass
class BadPropertyType(PropertyError):
    pass
class PropertyOverflow(PropertyError):
    pass
class NoSuchProperty(PropertyError):
    pass


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


SBFirst = {
           MSBFirst : "MSBFirst",
           LSBFirst : "LSBFirst"
           }

cdef char *XRGB = "XRGB"
cdef char *BGRX = "BGRX"
cdef char *ARGB = "ARGB"
cdef char *BGRA = "BGRA"
cdef char *RGB = "RGB"

cdef char *RGB_FORMATS[6]
RGB_FORMATS[0] = XRGB
RGB_FORMATS[1] = BGRX
RGB_FORMATS[2] = ARGB
RGB_FORMATS[3] = BGRA
RGB_FORMATS[4] = RGB
RGB_FORMATS[5] = NULL

cdef class XImageWrapper:
    cdef XImage *image                              #@DuplicatedSignature
    cdef int x
    cdef int y
    cdef int width                                  #@DuplicatedSignature
    cdef int height                                 #@DuplicatedSignature
    cdef int depth                                  #@DuplicatedSignature
    cdef int rowstride
    cdef int planes
    cdef char *pixel_format
    cdef char *pixels
    cdef object del_callback

    def __cinit__(self, int x, int y, int width, int height):
        self.image = NULL
        self.pixels = NULL
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.pixel_format = ""
        self.rowstride = 0
        self.planes = 0

    cdef set_image(self, XImage* image):
        self.image = image
        self.rowstride = self.image.bytes_per_line
        self.depth = self.image.depth
        if self.depth==24:
            if self.image.byte_order==MSBFirst:
                self.pixel_format = XRGB
            else:
                self.pixel_format = BGRX
        elif self.depth==32:
            if self.image.byte_order==MSBFirst:
                self.pixel_format = ARGB
            else:
                self.pixel_format = BGRA
        else:
            raise Exception("invalid image depth: %s bpp" % self.depth)
        assert self.pixel_format in RGB_FORMATS

    def __str__(self):
        return "XImageWrapper(%s: %s, %s, %s, %s)" % (self.pixel_format, self.x, self.y, self.width, self.height)

    def get_geometry(self):
        return self.x, self.y, self.width, self.height, self.depth

    def get_x(self):
        return self.x

    def get_y(self):
        return self.y

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height

    def get_rowstride(self):
        return self.rowstride

    def get_planes(self):
        return self.planes

    def get_depth(self):
        return self.depth

    def get_size(self):
        return self.rowstride * self.height

    def get_pixel_format(self):
        return self.pixel_format

    def get_pixels(self):
        if self.pixels!=NULL:
            return self.get_char_pixels()
        return self.get_image_pixels()

    def get_char_pixels(self):
        assert self.pixels!=NULL
        return PyBuffer_FromMemory(self.pixels, self.get_size())

    def get_image_pixels(self):
        assert self.image!=NULL
        return PyBuffer_FromMemory(self.image.data, self.get_size())

    def set_rowstride(self, rowstride):
        self.rowstride = rowstride

    def set_pixel_format(self, pixel_format):
        assert pixel_format in RGB_FORMATS, "invalid rgb_format: %s" % pixel_format
        cdef int i =0
        while RGB_FORMATS[i]!=pixel_format:
            i +=1
        self.pixel_format = RGB_FORMATS[i]

    def set_pixels(self, pixels):
        cdef const unsigned char * buf = NULL
        cdef Py_ssize_t buf_len = 0
        if self.pixels!=NULL:
            free(self.pixels)
            self.pixels = NULL
        #Note: we can't free the XImage, because it may
        #still be used somewhere else (see XShmWrapper)
        assert PyObject_AsReadBuffer(pixels, <const_void_pp> &buf, &buf_len)==0
        self.pixels = <char *> malloc(buf_len)
        assert self.pixels!=NULL
        memcpy(self.pixels, buf, buf_len)

    def free(self):                                     #@DuplicatedSignature
        debug("XImageWrapper.free()")
        self.free_image()
        self.free_pixels()

    def free_image(self):
        debug("XImageWrapper.free_image() image=%s", self.image!=NULL)
        if self.image!=NULL:
            XDestroyImage(self.image)
            self.image = NULL

    def free_pixels(self):
        debug("XImageWrapper.free_pixels() pixels=%s", self.pixels!=NULL)
        if self.pixels!=NULL:
            free(self.pixels)
            self.pixels = NULL


cdef class XShmWrapper(object):
    cdef Display *display                              #@DuplicatedSignature
    cdef XShmSegmentInfo shminfo
    cdef XImage *image
    cdef int width
    cdef int height
    cdef int ref_count
    cdef Bool closed

    def init(self, window):
        cdef Visual *visual
        cdef int depth
        cdef size_t size
        self.ref_count = 0
        self.closed = False
        self.shminfo.shmaddr = <char *> -1

        self.display = get_xdisplay_for(window)
        visual = _get_xvisual(window.get_visual())
        depth = window.get_depth()
        self.width, self.height = window.get_size()
        #add an extra pixel of height so we can
        #safely read a full rowstride on the last row,
        #even when starting at an X offset.
        self.image = XShmCreateImage(self.display, visual, depth,
                          ZPixmap, NULL, &self.shminfo,
                          self.width, self.height)
        xshm_debug("XShmWrapper.XShmCreateImage(%sx%s-%s) %s", self.width, self.height, depth, self.image!=NULL)
        if self.image==NULL:
            log.error("XShmWrapper.XShmCreateImage(%sx%s-%s) failed!", self.width, self.height, depth)
            self.free()
            return False
        # Get the shared memory:
        # (include an extra line to ensure we can read rowstride at a time,
        #  even on the last line, without reading past the end of the buffer)
        size = self.image.bytes_per_line * (self.image.height + 1)
        self.shminfo.shmid = shmget(IPC_PRIVATE, size, IPC_CREAT | 0777)
        xshm_debug("XShmWrapper.shmget(PRIVATE, %s bytes, %s) shmid=%s", size, IPC_CREAT | 0777, self.shminfo.shmid)
        if self.shminfo.shmid < 0:
            log.error("XShmWrapper.shmget(PRIVATE, %s bytes, %s) failed!", size, IPC_CREAT | 0777)
            self.free()
            return False
        # Attach:
        self.image.data = <char *> shmat(self.shminfo.shmid, NULL, 0)
        self.shminfo.shmaddr = self.image.data
        xshm_debug("XShmWrapper.shmat(%s, NULL, 0) %s", self.shminfo.shmid, self.shminfo.shmaddr != <char *> -1)
        if self.shminfo.shmaddr == <char *> -1:
            log.error("XShmWrapper.shmat(%s, NULL, 0) failed!", self.shminfo.shmid)
            self.free()
            return False

        # set as read/write, and attach to the display:
        self.shminfo.readOnly = False
        a = XShmAttach(self.display, &self.shminfo)
        xshm_debug("XShmWrapper.XShmAttach(..) %s", bool(a))
        if not a:
            log.error("XShmWrapper.XShmAttach(..) failed!")
            self.free()
            return False
        return True

    def get_image(self, xpixmap, x, y, w, h):
        assert self.image!=NULL
        if self.closed:
            return None
        if x+w>self.width:
            log.warn("XShmWrapper.get_image%s width overflow, image width is %s", (xpixmap, x, y, w, h), self.width)
            return None
        if y+h>self.height:
            log.warn("XShmWrapper.get_image%s height overflow, image height is %s", (xpixmap, x, y, w, h), self.height)
            return None
        if not XShmGetImage(self.display, xpixmap, self.image, 0, 0, 0xFFFFFFFF):
            log.warn("XShmWrapper.get_image%s XShmGetImage failed!", (xpixmap, x, y, w, h))
            return None
        self.ref_count += 1
        imageWrapper = XShmImageWrapper(x, y, w, h)
        imageWrapper.set_image(self.image)
        imageWrapper.set_free_callback(self.free_image)
        xshm_debug("XShmWrapper.get_image%s ref_count=%s, returning %s", (xpixmap, x, y, w, h), self.ref_count, imageWrapper)
        return imageWrapper

    def __dealloc__(self):                              #@DuplicatedSignature
        xshm_debug("XShmWrapper.__dealloc__() self=%s", self)
        self.cleanup()

    def cleanup(self):
        #ok, we want to free resources... problem is,
        #we may have handed out some XShmImageWrappers
        #and they will point to our Image XShm area.
        #so we have to wait until *they* are freed,
        #and rely on them telling us via the free_image callback.
        xshm_debug("XShmWrapper.cleanup() ref_count=%s", self.ref_count)
        self.closed = True
        if self.ref_count==0:
            self.free()

    def free_image(self):                               #@DuplicatedSignature
        self.ref_count -= 1
        xshm_debug("XShmWrapper.free_image() closed=%s, new ref_count=%s", self.closed, self.ref_count)
        if self.closed and self.ref_count==0:
            self.free()

    def free(self):                                     #@DuplicatedSignature
        assert self.ref_count==0 and self.closed
        has_shm = self.shminfo.shmaddr!=<char *> -1
        xshm_debug("XShmWrapper.free() has_shm=%s", has_shm)
        if has_shm:
            XShmDetach(self.display, &self.shminfo)
        if has_shm:
            shmdt(self.shminfo.shmaddr)
            self.shminfo.shmaddr = <char *> -1
        if self.image!=NULL:
            XDestroyImage(self.image)
            self.image = NULL


cdef class XShmImageWrapper(XImageWrapper):

    cdef object free_callback

    def __init__(self, *args):                      #@DuplicatedSignature
        self.free_callback = None

    def __str__(self):                              #@DuplicatedSignature
        return "XShmImageWrapper(%s: %s, %s, %s, %s)" % (self.pixel_format, self.x, self.y, self.width, self.height)

    def get_image_pixels(self):                     #@DuplicatedSignature
        cdef char *offset
        xshm_debug("XShmImageWrapper.get_image_pixels() self=%s", self)
        assert self.image!=NULL
        #calculate offset (assuming 4 bytes "pixelstride"):
        offset = self.image.data + (self.y * self.rowstride) + (4 * self.x)
        return PyBuffer_FromMemory(offset, self.get_size())

    def free(self):                                 #@DuplicatedSignature
        xshm_debug("XShmImageWrapper.free() free_callback=%s", self.free_callback)
        #ensure we never try to XDestroyImage:
        self.image = NULL
        self.free_pixels()
        if self.free_callback:
            cb = self.free_callback
            self.free_callback = None
            cb()
        xshm_debug("XShmImageWrapper.free() done")

    def set_free_callback(self, callback):
        self.free_callback = callback


class PixmapWrapper(object):
    "Reference count an X Pixmap that needs explicit cleanup."
    def __init__(self, display, xpixmap, width, height):     #@DuplicatedSignature
        self.display = display
        self.xpixmap = xpixmap
        self.width = width
        self.height = height

    def get_image(self, x, y, width, height):                #@DuplicatedSignature
        if self.xpixmap is None:
            log.warn("PixmapWrapper.get_pixels(%s, %s, %s, %s) xpixmap=%s", x, y, width, height, self.xpixmap)
            return  None
        debug("PixmapWrapper.get_pixels(%s, %s, %s, %s) xpixmap=%s, width=%s, height=%s", x, y, width, height, self.xpixmap, self.width, self.height)
        assert x+width<=self.width, "invalid width: %s (pixmap width is %s)" % (width, self.width)
        assert y+height<=self.height, "invalid height: %s (pixmap height is %s)" % (height, self.height)
        return get_image(self.display, self.xpixmap, x, y, width, height)

    def __del__(self):
        debug("PixmapWrapper.__del__() self.xpixmap=%s", self.xpixmap)
        if self.xpixmap is not None:
            XFreePixmap(get_xdisplay_for(self.display), self.xpixmap)
            self.xpixmap = None



cdef get_image(display, xpixmap, x, y, width, height):
    cdef Display * xdisplay                              #@DuplicatedSignature
    cdef XImage* ximage
    xdisplay = get_xdisplay_for(display)
    ximage = XGetImage(xdisplay, xpixmap, x, y, width, height, AllPlanes, ZPixmap)
    #log.info("get_pixels(..) ximage==NULL : %s", ximage==NULL)
    if ximage==NULL:
        info("get_pixels(..) failed to get XImage for xpixmap %s", xpixmap)
        return None
    xi = XImageWrapper(x, y, width, height)
    xi.set_image(ximage)
    return xi


def xcomposite_name_window_pixmap(window):
    cdef Display * display                              #@DuplicatedSignature
    cdef Window root_window
    cdef int x, y
    cdef unsigned int width, height, border, depth
    cdef Status status
    display = get_xdisplay_for(window)
    _ensure_XComposite_support(window)
    xpixmap = XCompositeNameWindowPixmap(display, get_xwindow(window))
    if xpixmap==XNone:
        return None
    status = XGetGeometry(display, xpixmap, &root_window,
                        &x, &y, &width, &height, &border, &depth)
    if status==0:
        info("failed to get pixmap dimensions for %s" % xpixmap)
        XFreePixmap(display, xpixmap)
        return None
    return PixmapWrapper(get_display_for(window), xpixmap, width, height)


def _ensure_XComposite_support(display_source):
    # We need NameWindowPixmap, but we don't need the overlay window
    # (v0.3) or the special manual-redirect clipping semantics (v0.4).
    _ensure_extension_support(display_source, 0, 2, "Composite",
                              XCompositeQueryExtension,
                              XCompositeQueryVersion)



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
                debug("found X11 extension %s with version %s.%s", extension, major, minor)
                if major == cmajor and minor <= cminor:
                    display.set_data(key, True)
                else:
                    raise ValueError("%s v%s.%s not supported; required: v%s.%s"
                                     % (extension, cmajor, cminor, major, minor))
        else:
            raise ValueError("X11 extension %s not available" % extension)
    if not display.get_data(key):
        raise ValueError("insufficient %s support in server" % extension)





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
        warn("already too many receivers for window %s: %s, adding %s to %s", window, len(receivers), receiver, receivers)
        import traceback
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


CursorNotify = 0
XKBNotify = 0
_x_event_signals = {}
event_type_names = {}
names_to_event_type = {}
#sometimes we may want to debug routing for certain X11 event types
debug_route_events = []

def get_error_text(code):
    if type(code)!=int:
        return code
    cdef Display * display                              #@DuplicatedSignature
    display = get_xdisplay_for(gtk.gdk.get_default_root_window())
    cdef char[128] buffer
    XGetErrorText(display, code, buffer, 128)
    return str(buffer[:128])

def get_XKB_event_base():
    cdef int opcode = 0
    cdef int event_base = 0
    cdef int error_base = 0
    cdef int major = 0
    cdef int minor = 0
    cdef Display * xdisplay                             #@DuplicatedSignature
    display = gtk.gdk.get_default_root_window().get_display()
    xdisplay = get_xdisplay_for(display)
    XkbQueryExtension(xdisplay, &opcode, &event_base, &error_base, &major, &minor)
    debug("get_XKB_event_base(%s)=%s", display.get_name(), int(event_base))
    return int(event_base)

def get_XFixes_event_base():
    cdef int event_base = 0                             #@DuplicatedSignature
    cdef int error_base = 0                             #@DuplicatedSignature
    cdef Display * xdisplay                             #@DuplicatedSignature
    display = gtk.gdk.get_default_root_window().get_display()
    xdisplay = get_xdisplay_for(display)
    XFixesQueryExtension(xdisplay, &event_base, &error_base)
    debug("get_XFixes_event_base(%s)=%s", display.get_name(), int(event_base))
    return int(event_base)

def get_XDamage_event_base():
    cdef int event_base = 0                             #@DuplicatedSignature
    cdef int error_base = 0                             #@DuplicatedSignature
    cdef Display * xdisplay                             #@DuplicatedSignature
    display = gtk.gdk.get_default_root_window().get_display()
    xdisplay = get_xdisplay_for(display)
    XDamageQueryExtension(xdisplay, &event_base, &error_base)
    debug("get_XDamage_event_base(%s)=%s", display.get_name(), int(event_base))
    return int(event_base)



def init_x11_events():
    global _x_event_signals, event_type_names, XKBNotify, CursorNotify, DamageNotify
    XKBNotify = get_XKB_event_base()
    CursorNotify = XFixesCursorNotify+get_XFixes_event_base()
    DamageNotify = XDamageNotify+get_XDamage_event_base()
    _x_event_signals = {
        MapRequest          : (None, "child-map-request-event"),
        ConfigureRequest    : (None, "child-configure-request-event"),
        FocusIn             : ("xpra-focus-in-event", None),
        FocusOut            : ("xpra-focus-out-event", None),
        ClientMessage       : ("xpra-client-message-event", None),
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
        #GenericEvent        : "GenericEvent",    #Old versions of X11 don't have this defined, ignore it
        }
    for k,v in event_type_names.items():
        names_to_event_type[v] = k
    debug("x_event_signals=%s", _x_event_signals)
    debug("event_type_names=%s", event_type_names)
    debug("names_to_event_type=%s", names_to_event_type)

    XPRA_X11_DEBUG_EVENTS = os.environ.get("XPRA_X11_DEBUG_EVENTS", "")
    if XPRA_X11_DEBUG_EVENTS=="*":
        debug_events = names_to_event_type.keys()
    else:
        debug_events = XPRA_X11_DEBUG_EVENTS.split(",")
    for n in debug_events:
        name = n.strip()
        if len(name)==0:
            continue
        event_type = names_to_event_type.get(name)
        if event_type is None:
            warn("could not find event type '%s' in %s", name, ", ".join(names_to_event_type.keys()))
        else:
            debug_route_events.append(event_type)
    if len(debug_route_events)>0:
        warn("debugging of X11 events enabled for: %s", [event_type_names.get(x, x) for x in debug_route_events])

#and change this debugging on the fly, programmatically:
def add_debug_route_event(event_type):
    global debug_route_events
    debug_route_events.append(event_type)
def remove_debug_route_event(event_type):
    global debug_route_events
    debug_route_events.remove(event_type)

def _route_event(event, signal, parent_signal):
    # Sometimes we get GDK events with event.window == None, because they are
    # for windows we have never created a GdkWindow object for, and GDK
    # doesn't do so just for this event.  As far as I can tell this only
    # matters for override redirect windows when they disappear, and we don't
    # care about those anyway.
    global debug_route_events
    l = debug
    if event.type in debug_route_events:
        l = info
    def _maybe_send_event(window, signal, event):
        handlers = window.get_data(_ev_receiver_key)
        if handlers is not None:
            # Copy the 'handlers' list, because signal handlers might cause items
            # to be added or removed from it while we are iterating:
            for handler in list(handlers):
                signals = gobject.signal_list_names(handler)
                if signal in signals:
                    l("  forwarding event to a %s handler's %s signal",
                        type(handler).__name__, signal)
                    handler.emit(signal, event)
                    l("  forwarded")
                else:
                    l("  not forwarding to %s handler, it has no %s signal (it has: %s)",
                        type(handler).__name__, signal, signals)
        else:
            l("  no handler registered for this window, ignoring event")

    l("%s event %s", event_type_names.get(event.type, event.type), event.serial)
    if event.window is None:
        l("  event.window is None, ignoring")
        assert event.type in (UnmapNotify, DestroyNotify), \
                "event window is None for event type %s!" % (event_type_names.get(event.type, event.type))
        return
    if event.window is event.delivered_to:
        if signal is not None:
            l("  delivering event to window itself")
            _maybe_send_event(event.window, signal, event)
        else:
            l("  received event on window itself but have no signal for that")
    else:
        if parent_signal is not None:
            l("  delivering event to parent window")
            _maybe_send_event(event.delivered_to, parent_signal, event)
        else:
            l("  received event on a parent window but have no parent signal")


def _gw(display, xwin):
    if xwin==0:
        return None
    gtk.gdk.error_trap_push()
    try:
        disp = get_display_for(display)
        win = gtk.gdk.window_foreign_new_for_display(disp, xwin)
        gtk.gdk.flush()
        error = gtk.gdk.error_trap_pop()
    except Exception, e:
        debug("cannot get gdk window for %s, %s: %s", display, xwin, e)
        error = gtk.gdk.error_trap_pop()
        if error:
            debug("ignoring XError %s in unwind", get_error_text(error))
        raise XError(e)
    if error:
        debug("cannot get gdk window for %s, %s: %s", display, xwin, get_error_text(error))
        raise XError(error)
    if win is None:
        debug("cannot get gdk window for %s, %s", display, xwin)
        raise XError(BadWindow)
    return win


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
    start = time.time()
    try:
        my_events = _x_event_signals
        event_args = my_events.get(e.type)
        if X11_DEBUG:
            msg = "x_event_filter event=%s/%s window=%s", event_args, event_type_names.get(e.type, e.type), e.xany.window
            info(*msg)
        if event_args is not None:
            d = wrap(<cGObject*>gdk_x11_lookup_xdisplay(e.xany.display))
            pyev = AdHocStruct()
            pyev.type = e.type
            pyev.send_event = e.xany.send_event
            pyev.display = d
            pyev.serial = e.xany.serial
            # Unmarshal:
            try:
                if e.type != XKBNotify:
                    pyev.delivered_to = _gw(d, e.xany.window)
                if e.type == MapRequest:
                    debug("MapRequest received")
                    pyev.window = _gw(d, e.xmaprequest.window)
                elif e.type == ConfigureRequest:
                    debug("ConfigureRequest received")
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
                    debug("FocusIn/FocusOut received")
                    pyev.window = _gw(d, e.xfocus.window)
                    pyev.mode = e.xfocus.mode
                    pyev.detail = e.xfocus.detail
                elif e.type == ClientMessage:
                    debug("ClientMessage received")
                    pyev.window = _gw(d, e.xany.window)
                    if long(e.xclient.message_type) > (long(2) ** 32):
                        warn("Xlib claims that this ClientEvent's 32-bit "
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
                        #_KDE_SPLASH_PROGRESS can be ignored silently
                        #we know about it and we don't care
                        if pyev.message_type!="_KDE_SPLASH_PROGRESS":
                            warn("FIXME: Ignoring ClientMessage type=%s with format=%s (!=32)" % (pyev.message_type, pyev.format))
                        return GDK_FILTER_CONTINUE
                    pieces = []
                    for i in xrange(5):
                        # Mask with 0xffffffff to prevent sign-extension on
                        # architectures where Python's int is 64-bits.
                        pieces.append(int(e.xclient.data.l[i]) & 0xffffffff)
                    pyev.data = tuple(pieces)
                elif e.type == MapNotify:
                    debug("MapNotify event received")
                    pyev.window = _gw(d, e.xmap.window)
                    pyev.override_redirect = e.xmap.override_redirect
                elif e.type == UnmapNotify:
                    debug("UnmapNotify event received")
                    pyev.window = _gw(d, e.xunmap.window)
                elif e.type == DestroyNotify:
                    debug("DestroyNotify event received")
                    pyev.window = _gw(d, e.xdestroywindow.window)
                elif e.type == PropertyNotify:
                    debug("PropertyNotify event received")
                    pyev.window = _gw(d, e.xany.window)
                    pyev.atom = trap.call_synced(get_pyatom, d,
                                                 e.xproperty.atom)
                elif e.type == ConfigureNotify:
                    debug("ConfigureNotify event received")
                    pyev.window = _gw(d, e.xconfigure.window)
                    pyev.x = e.xconfigure.x
                    pyev.y = e.xconfigure.y
                    pyev.width = e.xconfigure.width
                    pyev.height = e.xconfigure.height
                    pyev.border_width = e.xconfigure.border_width
                elif e.type == ReparentNotify:
                    debug("ReparentNotify event received")
                    pyev.window = _gw(d, e.xreparent.window)
                elif e.type == KeyPress:
                    debug("KeyPress event received")
                    pyev.window = _gw(d, e.xany.window)
                    pyev.hardware_keycode = e.xkey.keycode
                    pyev.state = e.xkey.state
                elif e.type == CursorNotify:
                    debug("Cursor event received")
                    pyev.window = _gw(d, e.xany.window)
                    cursor_e = <XFixesCursorNotifyEvent*>e
                    pyev.cursor_serial = cursor_e.cursor_serial
                    pyev.cursor_name = trap.call_synced(get_pyatom, d, cursor_e.cursor_name)
                elif e.type == XKBNotify:
                    # note we could just cast directly to XkbBellNotifyEvent
                    # but this would be dirty, and we may want to catch
                    # other types of XKB events in the future
                    xkb_e = <XkbAnyEvent*>e
                    debug("XKB event received xkb_type=%s", xkb_e.xkb_type)
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
                        debug("using bell_e.window=%s", bell_e.window)
                        pyev.window = _gw(d, bell_e.window)
                    else:
                        pyev.window = d.get_default_screen().get_root_window()
                        debug("bell using root window=%s", pyev.window)
                    pyev.event_only = bool(bell_e.event_only)
                    pyev.delivered_to = pyev.window
                    pyev.window_model = None
                    pyev.bell_name = get_pyatom(pyev.window, bell_e.name)
                    debug("XKB BellEvent: event=%r", pyev)
                elif e.type == DamageNotify:
                    debug("DamageNotify received")
                    damage_e = <XDamageNotifyEvent*>e
                    pyev.window = _gw(d, e.xany.window)
                    pyev.damage = damage_e.damage
                    pyev.x = damage_e.area.x
                    pyev.y = damage_e.area.y
                    pyev.width = damage_e.area.width
                    pyev.height = damage_e.area.height
            except XError, ex:
                if ex.msg==BadWindow:
                    msg = "Some window in our event disappeared before we could " \
                        + "handle the event %s/%s using %s; so I'm just ignoring it instead. python event=%s", e.type, event_type_names.get(e.type), event_args, pyev
                    if X11_DEBUG:
                        info(*msg)
                    else:
                        debug(*msg)
                else:
                    msg = "X11 error %s parsing the event %s/%s using %s; so I'm just ignoring it instead. python event=%s", get_error_text(ex.msg), e.type, event_type_names.get(e.type), event_args, pyev
                    error(*msg)
            else:
                _route_event(pyev, *event_args)
        if X11_DEBUG:
            msg = "x_event_filter event=%s/%s took %sms", event_args, event_type_names.get(e.type, e.type), int(100000*(time.time()-start))/100.0
            info(*msg)
    except (KeyboardInterrupt, SystemExit):
        debug("exiting on KeyboardInterrupt/SystemExit")
        gtk_main_quit_really()
    except:
        warn("Unhandled exception in x_event_filter:", exc_info=True)
    return GDK_FILTER_CONTINUE


def init_x11_filter():
    init_x11_events()
    gdk_window_add_filter(<cGdkWindow*>0, x_event_filter, <void*>0)
