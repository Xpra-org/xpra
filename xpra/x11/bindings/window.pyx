# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Dict, Any, Optional, List, Tuple
from xpra.gtk_common.error import XError

from xpra.x11.bindings.xlib cimport (
    Display, Drawable, Visual, Window, Bool, Pixmap, XID, Status, Atom, Time, CurrentTime, Cursor, XPointer,
    GrabModeAsync, XGrabPointer,
    Expose,
    XRectangle, XEvent, XClassHint,
    XWMHints, XSizeHints,
    XCreateWindow, XDestroyWindow, XIfEvent, PropertyNotify,
    XSetWindowAttributes,
    XWindowAttributes, XWindowChanges,
    XDefaultRootWindow,
    XInternAtom, XFree, XGetErrorText,
    XGetSelectionOwner, XSetSelectionOwner, XConvertSelection,
    XMapWindow, XMapRaised, XUnmapWindow, XWithdrawWindow, XReparentWindow, XIconifyWindow, XRaiseWindow,
    NextRequest, XSendEvent, XSelectInput, XAddToSaveSet, XRemoveFromSaveSet,
    XGetWindowAttributes, XGetWindowProperty, XDeleteProperty, XChangeProperty,
    XGetWMNormalHints, XSetWMNormalHints, XGetWMHints, XGetWMProtocols,
    XGetGeometry, XTranslateCoordinates, XConfigureWindow,
    XMoveResizeWindow, XResizeWindow, XMoveWindow,
    XGetInputFocus, XSetInputFocus,
    XAllocClassHint, XAllocSizeHints, XGetClassHint, XSetClassHint,
    XQueryTree,
    XKillClient,
)
from libc.stdlib cimport free, malloc       #pylint: disable=syntax-error
from libc.string cimport memset

from xpra.log import Logger
log = Logger("x11", "bindings", "window")

###################################
# Headers, python magic
###################################

######
# Xlib primitives and constants
######

DEF XNone = 0


cdef extern from "X11/Xlib.h":
    int CWX
    int CWY
    int CWWidth
    int CWHeight
    int InputOnly
    int InputOutput
    int RevertToParent
    int ClientMessage
    int ButtonPress
    int Button1
    int Button2
    int Button3
    int SelectionNotify
    int ConfigureNotify

    int CopyFromParent

    int CWEventMask
    int CWColormap
    int CWBorderWidth
    int CWSibling
    int CWStackMode

    int NoEventMask
    int KeyPressMask
    int KeyReleaseMask
    int ButtonPressMask
    int ButtonReleaseMask
    int EnterWindowMask
    int LeaveWindowMask
    int PointerMotionMask
    int PointerMotionHintMask
    int Button1MotionMask
    int Button2MotionMask
    int Button3MotionMask
    int Button4MotionMask
    int Button5MotionMask
    int ButtonMotionMask
    int KeymapStateMask
    int ExposureMask
    int VisibilityChangeMask
    int StructureNotifyMask
    int ResizeRedirectMask
    int SubstructureNotifyMask
    int SubstructureRedirectMask
    int FocusChangeMask
    int PropertyChangeMask
    int ColormapChangeMask
    int OwnerGrabButtonMask

    int AnyPropertyType
    int Success
    int PropModeReplace
    int USPosition
    int PPosition
    int USSize
    int PSize
    int PMinSize
    int IsUnmapped
    int XNone
    int PMaxSize
    int PBaseSize
    int PResizeInc
    int PAspect
    int PWinGravity
    int InputHint
    int StateHint
    int IconPixmapHint
    int IconWindowHint
    int IconPositionHint
    int IconMaskHint
    int WindowGroupHint
    int XUrgencyHint
    int IconicState
    int NormalState
    int NotifyNormal
    int NotifyGrab
    int NotifyUngrab
    int NotifyWhileGrabbed
    int NotifyNonlinearVirtual
    int NotifyAncestor
    int NotifyVirtual
    int NotifyInferior
    int NotifyNonlinear
    int NotifyPointer
    int NotifyPointerRoot
    int NotifyDetailNone



constants = {
    "CWX"               : CWX,
    "CWY"               : CWY,
    "CWWidth"           : CWWidth,
    "CWHeight"          : CWHeight,
    "CurrentTime"       : CurrentTime,
    "IsUnmapped"        : IsUnmapped,
    "InputOnly"         : InputOnly,
    "RevertToParent"    : RevertToParent,
    "ClientMessage"     : ClientMessage,
    "ButtonPress"       : ButtonPress,
    "Button1"           : Button1,
    "Button2"           : Button2,
    "Button3"           : Button3,
    "NoEventMask"       : NoEventMask,
    "SelectionNotify"   : SelectionNotify,
    "ConfigureNotify"   : ConfigureNotify,
    "StructureNotifyMask" : StructureNotifyMask,
    "CWBorderWidth"     : CWBorderWidth,
    "CWSibling"         : CWSibling,
    "CWStackMode"       : CWStackMode,
    "SubstructureNotifyMask"   : SubstructureNotifyMask,
    "SubstructureRedirectMask" : SubstructureRedirectMask,
    "FocusChangeMask"   : FocusChangeMask,
    "ExposureMask"      : ExposureMask,
    "PropertyChangeMask": PropertyChangeMask,
    "AnyPropertyType"   : AnyPropertyType,
    "Success"           : Success,
    "PropModeReplace"   : PropModeReplace,
    "USPosition"        : USPosition,
    "PPosition"         : PPosition,
    "USSize"            : USSize,
    "PSize"             : PSize,
    "PMinSize"          : PMinSize,
    "XNone"             : XNone,
    "PMaxSize"          : PMaxSize,
    "PBaseSize"         : PBaseSize,
    "PResizeInc"        : PResizeInc,
    "PAspect"           : PAspect,
    "PWinGravity"       : PWinGravity,
    "InputHint"         : InputHint,
    "StateHint"         : StateHint,
    "IconPixmapHint"    : IconPixmapHint,
    "IconWindowHint"    : IconWindowHint,
    "IconPositionHint"  : IconPositionHint,
    "IconMaskHint"      : IconMaskHint,
    "WindowGroupHint"   : WindowGroupHint,
    "XUrgencyHint"      : XUrgencyHint,
    "IconicState"       : IconicState,
    "NormalState"       : NormalState,
    "NotifyNormal"      : NotifyNormal,
    "NotifyGrab"        : NotifyGrab,
    "NotifyUngrab"      : NotifyUngrab,
    "NotifyWhileGrabbed" : NotifyWhileGrabbed,
    "NotifyNonlinear"   : NotifyNonlinear,
    "NotifyNonlinearVirtual" : NotifyNonlinearVirtual,
    "NotifyAncestor"    : NotifyAncestor,
    "NotifyVirtual"     : NotifyVirtual,
    "NotifyInferior"    : NotifyInferior,
    "NotifyNonlinearVirtual" : NotifyNonlinearVirtual,
    "NotifyPointer"     : NotifyPointer,
    "NotifyPointerRoot" : NotifyPointerRoot,
    "NotifyDetailNone"  : NotifyDetailNone,
    }


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
    Window XCompositeGetOverlayWindow(Display *dpy, Window window)
    void XCompositeReleaseOverlayWindow(Display *dpy, Window window)


cdef extern from "X11/extensions/shape.h":
    Bool XShapeQueryExtension(Display *display, int *event_base, int *error_base)
    Status XShapeQueryVersion(Display *display, int *major_version, int *minor_version)
    Status XShapeQueryExtents(Display *display, Window window, Bool *bounding_shaped, int *x_bounding, int *y_bounding, unsigned int *w_bounding, unsigned int *h_bounding, Bool *clip_shaped, int *x_clip, int *y_clip, unsigned int *w_clip, unsigned int *h_clip)
    void XShapeSelectInput(Display *display, Window window, unsigned long mask)
    unsigned long XShapeInputSelected(Display *display, Window window)
    XRectangle *XShapeGetRectangles(Display *display, Window window, int kind, int *count, int *ordering)

    void XShapeCombineRectangles(Display *display, Window dest, int dest_kind, int x_off, int y_off, XRectangle *rectangles, int n_rects, int op, int ordering)


    cdef int ShapeBounding
    cdef int ShapeClip
    cdef int ShapeInput
SHAPE_KIND = {
                ShapeBounding   : "Bounding",
                ShapeClip       : "Clip",
                ShapeInput      : "ShapeInput",
              }

###################################
# Xfixes: cursor events
###################################
cdef extern from "X11/extensions/xfixeswire.h":
    unsigned long XFixesDisplayCursorNotifyMask
    void XFixesSelectCursorInput(Display *, Window w, long mask)

    unsigned int XFixesSetSelectionOwnerNotifyMask
    unsigned int XFixesSelectionWindowDestroyNotifyMask
    unsigned int XFixesSelectionClientCloseNotifyMask

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

    Bool XFixesQueryExtension(Display *, int *event_base, int *error_base)
    XFixesCursorImage* XFixesGetCursorImage(Display *)

    ctypedef XID XserverRegion

    XserverRegion XFixesCreateRegion(Display *dpy, XRectangle *rectangles, int nrectangles)
    void XFixesDestroyRegion(Display *dpy, XserverRegion region)

    void XFixesSetWindowShapeRegion(Display *dpy, Window win, int shape_kind, int x_off, int y_off, XserverRegion region)

    void XFixesSelectSelectionInput(Display *dpy, Window win, Atom selection, unsigned long eventMask)


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
    void XDamageSubtract(Display *, Damage, XserverRegion repair, XserverRegion parts)


cdef inline long cast_to_long(i):
    if i < 0:
        return <long>i
    else:
        return <long><unsigned long>i


class PropertyError(Exception):
    pass
class BadPropertyType(PropertyError):
    pass
class PropertyOverflow(PropertyError):
    pass


from xpra.x11.bindings.core cimport X11CoreBindingsInstance

cdef int CONFIGURE_GEOMETRY_MASK = CWX | CWY | CWWidth | CWHeight

cdef X11WindowBindingsInstance singleton = None
def X11WindowBindings():
    global singleton
    if singleton is None:
        singleton = X11WindowBindingsInstance()
    return singleton

cdef class X11WindowBindingsInstance(X11CoreBindingsInstance):

    cdef object has_xshape

    def __cinit__(self):
        self.has_xshape = None

    def __repr__(self):
        return "X11WindowBindings(%s)" % self.display_name

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
    cdef ensure_extension_support(self, major, minor, extension,
                                   Bool (*query_extension)(Display*, int*, int*),
                                   Status (*query_version)(Display*, int*, int*)):
        cdef int event_base = 0, ignored = 0
        if not (query_extension)(self.display, &event_base, &ignored):
            raise ValueError("X11 extension %s not available" % extension)
        log("X11 extension %s event_base=%i", extension, event_base)
        cdef int cmajor = major, cminor = minor
        if (query_version)(self.display, &cmajor, &cminor):
            # See X.org bug #14511:
            log("found X11 extension %s with version %i.%i", extension, major, minor)
            if cmajor<major or (cmajor==major and cminor<minor):
                raise ValueError("%s v%i.%i not supported; required: v%i.%i"
                                 % (extension, cmajor, cminor, major, minor))


    def get_all_x11_windows(self):
        cdef Window root = XDefaultRootWindow(self.display);
        return self.get_all_children(root)

    def get_all_children(self, Window xid):
        self.context_check("get_all_children")
        cdef Window root = XDefaultRootWindow(self.display)
        cdef Window parent = 0
        cdef Window * children = <Window *> 0
        cdef unsigned int i, nchildren = 0
        windows = []
        try:
            if not XQueryTree(self.display,
                              xid,
                              &root, &parent, &children, &nchildren):
                return []
            for i in range(nchildren):
                windows.append(children[i])
        finally:
            if nchildren > 0 and children != NULL:
                XFree(children)
        for window in tuple(windows):
            windows += self.get_all_children(window)
        return windows


    def get_absolute_position(self, Window xid):
        self.context_check("get_absolute_position")
        cdef Window root = XDefaultRootWindow(self.display)
        cdef int dest_x = 0, dest_y = 0
        cdef Window child = 0
        if not XTranslateCoordinates(self.display, xid,
                                     root,
                                     0, 0,
                                     &dest_x, &dest_y, &child):
            return None
        return dest_x, dest_y


    def MapWindow(self, Window xwindow):
        self.context_check("MapWindow")
        XMapWindow(self.display, xwindow)

    def MapRaised(self, Window xwindow):
        self.context_check("MapRaised")
        XMapRaised(self.display, xwindow)

    def Withdraw(self, Window xwindow, int screen_number=0):
        self.context_check("Withdraw")
        return XWithdrawWindow(self.display, xwindow, screen_number)

    def Reparent(self, Window xwindow, Window xparent, int x, int y):
        self.context_check("Reparent")
        XReparentWindow(self.display, xwindow, xparent, x, y)

    def Iconify(self, Window xwindow, int screen_number=0):
        self.context_check("Iconify")
        return XIconifyWindow(self.display, xwindow, screen_number)

    ###################################
    # XUnmapWindow
    ###################################
    def Unmap(self, Window xwindow):
        self.context_check("Unmap")
        cdef unsigned long serial = NextRequest(self.display)
        XUnmapWindow(self.display, xwindow)
        return serial


    def getWindowAttributes(self, Window xwindow):
        self.context_check("getWindowAttributes")
        cdef XWindowAttributes attrs
        cdef Status status = XGetWindowAttributes(self.display, xwindow, &attrs)
        if status==0:
            return None
        return {
            "geometry"  : (attrs.x, attrs.y, attrs.width, attrs.height, attrs.border_width),
            "depth"     : attrs.depth,
            "visual"    : {
                "visual-id"     : attrs.visual.visualid,
                #"class"         : attrs.visual.c_class,
                "red-mask"      : attrs.visual.red_mask,
                "green-mask"    : attrs.visual.green_mask,
                "blue-mask"     : attrs.visual.blue_mask,
                "bits-per-rgb"  : attrs.visual.bits_per_rgb,
                "map_entries"   : attrs.visual.map_entries,
                },
            "bit-gravity" : attrs.bit_gravity,
            "win-gravity" : attrs.win_gravity,
            "backing-store" : attrs.backing_store,
            "backing-planes" : attrs.backing_planes,
            "backing-pixel" : attrs.backing_pixel,
            "save-under"    : bool(attrs.save_under),
            #"colormap"  : 0,
            "map-installed" : attrs.map_installed,
            "map-state" : attrs.map_state,
            "all-events-mask" : attrs.all_event_masks,
            "your_event_mask"   : attrs.your_event_mask,
            "do-not-propagate-mask" : attrs.do_not_propagate_mask,
            "override-redirect"     : attrs.override_redirect,
            }

    def getEventMask(self, Window xwindow):
        self.context_check("getEventMask")
        cdef XWindowAttributes attrs
        cdef Status status = XGetWindowAttributes(self.display, xwindow, &attrs)
        if status==0:
            return 0
        return attrs.your_event_mask;

    def setEventMask(self, Window xwindow, int mask):
        self.context_check("setEventMask")
        XSelectInput(self.display, xwindow, mask)


    # Mapped status
    def is_mapped(self, Window xwindow):
        self.context_check("is_mapped")
        cdef XWindowAttributes attrs
        cdef Status status = XGetWindowAttributes(self.display, xwindow, &attrs)
        if status==0:
            return False
        return attrs.map_state != IsUnmapped

    # Override-redirect status
    def is_override_redirect(self, Window xwindow):
        self.context_check("is_override_redirect")
        cdef XWindowAttributes or_attrs
        cdef Status status = XGetWindowAttributes(self.display, xwindow, &or_attrs)
        if status==0:
            return False
        return or_attrs.override_redirect

    # Mapped status
    def is_inputonly(self, Window xwindow):
        self.context_check("is_inputonly")
        cdef XWindowAttributes attrs
        cdef Status status = XGetWindowAttributes(self.display, xwindow, &attrs)
        if status==0:
            return False
        return attrs._class==InputOnly


    def geometry_with_border(self, Window xwindow):
        self.context_check("geometry_with_border")
        cdef XWindowAttributes geom_attrs
        cdef Status status = XGetWindowAttributes(self.display, xwindow, &geom_attrs)
        if status==0:
            return None
        return (geom_attrs.x, geom_attrs.y, geom_attrs.width, geom_attrs.height, geom_attrs.border_width)

    def get_depth(self, Drawable d):
        self.context_check("get_depth")
        cdef Window root
        cdef int x, y
        cdef unsigned int width, height, border_width, depth
        if not XGetGeometry(self.display, d, &root,
                        &x, &y, &width, &height, &border_width, &depth):
            return 0
        return depth

    # Focus management
    def XSetInputFocus(self, Window xwindow, object time=CurrentTime):
        self.context_check("XSetInputFocus")
        # Always does RevertToParent
        XSetInputFocus(self.display, xwindow, RevertToParent, time)

    def XGetInputFocus(self):
        #context check not needed!
        cdef Window w = 0
        cdef int revert_to = 0
        XGetInputFocus(self.display, &w, &revert_to)
        return int(w), int(revert_to)

    def XRaiseWindow(self, Window window):
        self.context_check("XRaiseWindow")
        XRaiseWindow(self.display, window)

    ###################################
    # XKillClient
    ###################################
    def XKillClient(self, Window xwindow):
        self.context_check("XKillClient")
        return XKillClient(self.display, xwindow)


    ###################################
    # Shape
    ###################################
    def displayHasXShape(self):
        cdef int event_base = 0, ignored = 0
        cdef int cmajor, cminor
        if self.has_xshape is not None:
            pass
        elif not XShapeQueryExtension(self.display, &event_base, &ignored):
            log.warn("X11 extension XShape not available")
            self.has_xshape = False
        else:
            log("X11 extension XShape event_base=%i", event_base)
            if not XShapeQueryVersion(self.display, &cmajor, &cminor):
                log.warn("XShape version query failed")
                self.has_xshape = False
            else:
                log("found X11 extension XShape with version %i.%i", cmajor, cminor)
                self.has_xshape = True
        log("displayHasXShape()=%s", self.has_xshape)
        return self.has_xshape

    def XShapeSelectInput(self, Window window):
        self.context_check("XShapeSelectInput")
        cdef int ShapeNotifyMask = 1
        XShapeSelectInput(self.display, window, ShapeNotifyMask)

    def XShapeQueryExtents(self, Window window):
        self.context_check("XShapeQueryExtents")
        cdef Bool bounding_shaped, clip_shaped
        cdef int x_bounding, y_bounding, x_clip, y_clip
        cdef unsigned int w_bounding, h_bounding, w_clip, h_clip
        if not XShapeQueryExtents(self.display, window,
                                  &bounding_shaped, &x_bounding, &y_bounding, &w_bounding, &h_bounding,
                                  &clip_shaped, &x_clip, &y_clip, &w_clip, &h_clip):
            return None
        return (
                (bounding_shaped, x_bounding, y_bounding, w_bounding, h_bounding),
                (clip_shaped, x_clip, y_clip, w_clip, h_clip)
                )

    def XShapeGetRectangles(self, Window window, int kind):
        self.context_check("XShapeGetRectangles")
        cdef int count, ordering
        cdef XRectangle* rect = XShapeGetRectangles(self.display, window, kind, &count, &ordering)
        if rect==NULL or count<=0:
            return []
        rectangles = []
        cdef int i
        for i in range(count):
            rectangles.append((rect[i].x, rect[i].y, rect[i].width, rect[i].height))
        return rectangles

    def XShapeCombineRectangles(self, Window window, int kind, int x_off, int y_off, rectangles):
        self.context_check("XShapeCombineRectangles")
        cdef int n_rects = len(rectangles)
        cdef int op = 0     #SET
        cdef int ordering = 0   #Unsorted
        cdef size_t l = sizeof(XRectangle) * n_rects
        cdef XRectangle *rects = <XRectangle*> malloc(l)
        if rects==NULL:
            raise RuntimeError("failed to allocate %i bytes of memory for xshape rectangles" % l)
        cdef int i = 0
        for r in rectangles:
            rects[i].x = r[0]
            rects[i].y = r[1]
            rects[i].width = r[2]
            rects[i].height = r[3]
            i += 1
        XShapeCombineRectangles(self.display, window, kind, x_off, y_off,
                                rects, n_rects, op, ordering)
        free(rects)


    ###################################
    # Composite
    ###################################
    def ensure_XComposite_support(self):
        # We need NameWindowPixmap, but we don't need the overlay window
        # (v0.3) or the special manual-redirect clipping semantics (v0.4).
        self.ensure_extension_support(0, 2, "Composite",
                                  XCompositeQueryExtension,
                                  XCompositeQueryVersion)

    def displayHasXComposite(self):
        try:
            self.ensure_XComposite_support()
            return  True
        except Exception as e:
            log.error("%s", e)
        return False

    def XCompositeRedirectWindow(self, Window xwindow):
        self.context_check("XCompositeRedirectWindow")
        XCompositeRedirectWindow(self.display, xwindow, CompositeRedirectManual)

    def XCompositeRedirectSubwindows(self, Window xwindow):
        self.context_check("XCompositeRedirectSubwindows")
        XCompositeRedirectSubwindows(self.display, xwindow, CompositeRedirectManual)

    def XCompositeUnredirectWindow(self, Window xwindow):
        self.context_check("XCompositeUnredirectWindow")
        XCompositeUnredirectWindow(self.display, xwindow, CompositeRedirectManual)

    def XCompositeUnredirectSubwindows(self, Window xwindow):
        self.context_check("XCompositeUnredirectSubwindows")
        XCompositeUnredirectSubwindows(self.display, xwindow, CompositeRedirectManual)

    def XCompositeGetOverlayWindow(self, Window window):
        self.context_check("XCompositeGetOverlayWindow")
        return XCompositeGetOverlayWindow(self.display, window)

    def XCompositeReleaseOverlayWindow(self, Window window):
        self.context_check("XCompositeReleaseOverlayWindow")
        XCompositeReleaseOverlayWindow(self.display, window)

    def AllowInputPassthrough(self, Window window):
        self.context_check("AllowInputPassthrough")
        cdef XserverRegion region = XFixesCreateRegion(self.display, NULL, 0)
        XFixesSetWindowShapeRegion(self.display, window, ShapeBounding, 0, 0, 0)
        XFixesSetWindowShapeRegion(self.display, window, ShapeInput, 0, 0, region)
        XFixesDestroyRegion(self.display, region)


    ###################################
    # Xdamage
    ###################################
    def ensure_XDamage_support(self):
        self.ensure_extension_support(1, 0, "DAMAGE",
                                  XDamageQueryExtension,
                                  XDamageQueryVersion)

    def XDamageCreate(self, Window xwindow):
        self.context_check("XDamageCreate")
        return XDamageCreate(self.display, xwindow, XDamageReportDeltaRectangles)

    def XDamageDestroy(self, Damage handle):
        self.context_check("XDamageDestroy")
        XDamageDestroy(self.display, handle)

    def XDamageSubtract(self, Damage handle):
        self.context_check("XDamageSubtract")
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
        XDamageSubtract(self.display, handle, XNone, XNone)


    ###################################
    # Smarter convenience wrappers
    ###################################

    def XGetSelectionOwner(self, atom):
        self.context_check("XGetSelectionOwner")
        return XGetSelectionOwner(self.display, self.xatom(atom))

    def XSetSelectionOwner(self, Window xwindow, atom, time=CurrentTime):
        self.context_check("XSetSelectionOwner")
        return XSetSelectionOwner(self.display, self.xatom(atom), xwindow, time)

    def sendClientMessage(self, Window xtarget, Window xwindow, int propagate, int event_mask,
                          message_type, data0=0, data1=0, data2=0, data3=0, data4=0):
        self.context_check("sendClientMessage")
        # data0 etc. are passed through get_xatom, so they can be integers, which
        # are passed through directly, or else they can be strings, which are
        # converted appropriately.
        cdef XEvent e
        log("sendClientMessage(%#x, %#x, %#x, %#x, %s, %s, %s, %s, %s, %s)", xtarget, xwindow, propagate, event_mask,
                                        message_type, data0, data1, data2, data3, data4)
        e.type = ClientMessage
        e.xany.display = self.display
        e.xany.window = xwindow
        e.xclient.message_type = self.xatom(message_type)
        e.xclient.format = 32
        e.xclient.data.l[0] = cast_to_long(self.xatom(data0))
        e.xclient.data.l[1] = cast_to_long(self.xatom(data1))
        e.xclient.data.l[2] = cast_to_long(self.xatom(data2))
        e.xclient.data.l[3] = cast_to_long(self.xatom(data3))
        e.xclient.data.l[4] = cast_to_long(self.xatom(data4))
        cdef Status s = XSendEvent(self.display, xtarget, propagate, event_mask, &e)
        if s == 0:
            raise ValueError("failed to serialize ClientMessage")

    def sendClick(self, Window xtarget, int button, onoff, x_root, y_root, x, y):
        self.context_check("sendClick")
        cdef Window r = XDefaultRootWindow(self.display)
        log("sending message to %#x", xtarget)
        cdef XEvent e
        e.type = ButtonPress
        e.xany.display = self.display
        e.xany.window = xtarget
        #e.xclient.message_type = xatom(message_type)
        e.xclient.format = 32
        if button==1:
            e.xbutton.button = Button1
        elif button==2:
            e.xbutton.button = Button2
        else:
            e.xbutton.button = Button3
        e.xbutton.same_screen = True
        e.xbutton.root = r
        e.xbutton.x_root = x_root
        e.xbutton.y_root = y_root
        e.xbutton.x = x
        e.xbutton.y = y
        e.xbutton.state = int(onoff)
        cdef Status s = XSendEvent(self.display, xtarget, False, 0, &e)
        if s == 0:
            raise ValueError("failed to serialize ButtonPress Message")

    def send_xembed_message(self, Window xwindow, opcode, detail, data1, data2):
        """
         Display* dpy, /* display */
         Window w, /* receiver */
         long message, /* message opcode */
         long detail  /* message detail */
         long data1  /* message data 1 */
         long data2  /* message data 2 */
         """
        self.context_check("send_xembed_message")
        cdef XEvent e
        e.xany.display = self.display
        e.xany.window = xwindow
        e.xany.type = ClientMessage
        e.xclient.message_type = self.xatom("_XEMBED")
        e.xclient.format = 32
        e.xclient.data.l[0] = CurrentTime
        e.xclient.data.l[1] = opcode
        e.xclient.data.l[2] = detail
        e.xclient.data.l[3] = data1
        e.xclient.data.l[4] = data2
        s = XSendEvent(self.display, xwindow, False, NoEventMask, &e)
        if s == 0:
            raise ValueError("failed to serialize XEmbed Message")

    def send_expose(self, Window xwindow, int x, int y, int width, int height, int count=0):
        cdef XEvent e
        e.xany.display = self.display
        e.xany.window = xwindow
        e.xany.type = Expose
        e.xexpose.x = x
        e.xexpose.y = y
        e.xexpose.width = width
        e.xexpose.height = height
        e.xexpose.count = count
        s = XSendEvent(self.display, xwindow, False, NoEventMask, &e)
        if s == 0:
            raise ValueError("failed to serialize XExpose Message")

    ###################################
    # Clipboard
    ###################################
    def selectXFSelectionInput(self, Window window, selection_str):
        self.context_check("selectXFSelectionInput")
        cdef unsigned long event_mask = (
            XFixesSetSelectionOwnerNotifyMask |
            XFixesSelectionWindowDestroyNotifyMask |
            XFixesSelectionClientCloseNotifyMask
            )
        cdef Atom selection = self.xatom(selection_str)
        XFixesSelectSelectionInput(self.display, window, selection, event_mask)

    def selectSelectionInput(self, Window xwindow):
        self.context_check("selectSelectionInput")
        self.addXSelectInput(xwindow, SelectionNotify)

    def sendSelectionNotify(self, Window xwindow, selection, target, property, time=CurrentTime):
        self.context_check("sendSelectionNotify")
        cdef XEvent e
        e.type = SelectionNotify
        e.xselection.requestor = xwindow
        e.xselection.selection = self.xatom(selection)
        e.xselection.target = self.xatom(target)
        e.xselection.time = time
        if property:
            e.xselection.property = self.xatom(property)
        else:
            e.xselection.property = 0
        cdef Status s = XSendEvent(self.display, xwindow, True, 0, &e)
        if s == 0:
            raise ValueError("failed to serialize SelectionNotify")

    def ConvertSelection(self, selection, target, property, Window requestor, time=CurrentTime):
        self.context_check("ConvertSelection")
        return XConvertSelection(self.display, self.xatom(selection), self.xatom(target),
                                 self.xatom(property), requestor, time)

    def sendConfigureNotify(self, Window xwindow):
        self.context_check("sendConfigureNotify")
        cdef Window root_window = XDefaultRootWindow(self.display)

        # Get basic attributes
        cdef XWindowAttributes attrs
        XGetWindowAttributes(self.display, xwindow, &attrs)

        # Figure out where the window actually is in root coordinate space
        cdef int dest_x = 0, dest_y = 0
        cdef Window child = 0
        if not XTranslateCoordinates(self.display, xwindow,
                                     root_window,
                                     0, 0,
                                     &dest_x, &dest_y, &child):
            # Window seems to have disappeared, so never mind.
            log("couldn't TranslateCoordinates (maybe window is gone)")
            return

        # Send synthetic ConfigureNotify (ICCCM 4.2.3, for example)
        cdef XEvent e
        e.type = ConfigureNotify
        e.xconfigure.event = xwindow
        e.xconfigure.window = xwindow
        e.xconfigure.x = dest_x
        e.xconfigure.y = dest_y
        e.xconfigure.width = attrs.width
        e.xconfigure.height = attrs.height
        e.xconfigure.border_width = attrs.border_width
        e.xconfigure.above = XNone
        e.xconfigure.override_redirect = attrs.override_redirect

        cdef Status s = XSendEvent(self.display, xwindow, False, StructureNotifyMask, &e)
        if s == 0:
            raise ValueError("failed to serialize ConfigureNotify")

    def CreateCorralWindow(self, Window parent, Window xid, int x, int y):
        self.context_check("CreateCorralWindow")
        #copy most attributes from the window we will wrap:
        cdef int ox, oy
        cdef Window root
        cdef unsigned int width, height, border_width, depth
        if not XGetGeometry(self.display, xid, &root,
                        &ox, &oy, &width, &height, &border_width, &depth):
            return None
        cdef XSetWindowAttributes attributes
        memset(<void*> &attributes, 0, sizeof(XSetWindowAttributes))
        # We enable PropertyChangeMask so that we can call
        # get_server_time on this window.
        attributes.event_mask = PropertyChangeMask | StructureNotifyMask | SubstructureNotifyMask
        #get depth from parent window:
        cdef int px, py
        cdef unsigned int pw, ph, pborder, pdepth
        if not XGetGeometry(self.display, parent, &root,
                        &px, &py, &pw, &ph, &pborder, &pdepth):
            return None
        cdef unsigned long valuemask = CWEventMask
        cdef Window window = XCreateWindow(self.display, parent,
                                           x, y, width, height, 0, pdepth,
                                           InputOutput, <Visual*> CopyFromParent,
                                           valuemask, &attributes)
        return window

    def DestroyWindow(self, Window w):
        self.context_check("DestroyWindow")
        return XDestroyWindow(self.display, w)

    def ConfigureWindow(self, Window xwindow,
                        int x, int y, int width, int height, int border=0,
                        int sibling=0, int stack_mode=0,
                        int value_mask=CONFIGURE_GEOMETRY_MASK):
        self.context_check("ConfigureWindow")
        cdef XWindowChanges changes
        changes.x = x
        changes.y = y
        changes.width = width
        changes.height = height
        changes.border_width = border
        changes.sibling = sibling
        changes.stack_mode = stack_mode
        XConfigureWindow(self.display, xwindow, value_mask, &changes)

    def configure(self, Window xwindow, x, y, width, height, fields=None):
        # Reconfigure the window.  We have to use XConfigureWindow directly
        # instead of GdkWindow.resize, because GDK does not give us any way to
        # squash the border.

        # The caller can pass an XConfigureWindow-style fields mask to turn off
        # some of these bits; this is useful if they are pulling such a field out
        # of a ConfigureRequest (along with the other arguments they are passing
        # to us).  This also means we need to be careful to zero out any bits
        # besides these, because they could be set to anything.
        self.context_check("configureAndNotify")
        cdef int geom_flags = CWX | CWY | CWWidth | CWHeight
        if fields is None:
            fields = geom_flags
        else:
            fields = fields & geom_flags
        # But we always unconditionally squash the border to zero.
        fields = fields | CWBorderWidth
        self.ConfigureWindow(xwindow, x, y, width, height, value_mask=fields)

    def configureAndNotify(self, Window xwindow, x, y, width, height, fields=None):
        self.configure(xwindow, x, y, width, height, fields)
        # Tell the client.
        self.sendConfigureNotify(xwindow)

    def MoveResizeWindow(self, Window xwindow, int x, int y, int width, int height):
        self.context_check("MoveResizeWindow")
        return bool(XMoveResizeWindow(self.display, xwindow, x, y, width, height))

    def ResizeWindow(self, Window xwindow, int width, int height):
        self.context_check("ResizeWindow")
        return bool(XResizeWindow(self.display, xwindow, width, height))

    def MoveWindow(self, Window xwindow, int x, int y):
        self.context_check("MoveWindow")
        return bool(XMoveWindow(self.display, xwindow, x, y))

    def addDefaultEvents(self, Window xwindow):
        self.context_check("addDefaultEvents")
        ADDMASK = StructureNotifyMask | PropertyChangeMask | FocusChangeMask | PointerMotionMask | PointerMotionHintMask | ButtonMotionMask
        self.addXSelectInput(xwindow, ADDMASK)

    def addXSelectInput(self, Window xwindow, add_mask):
        self.context_check("addXSelectInput")
        cdef XWindowAttributes curr
        XGetWindowAttributes(self.display, xwindow, &curr)
        mask = curr.your_event_mask
        mask = mask | add_mask
        XSelectInput(self.display, xwindow, mask)

    def substructureRedirect(self, Window xwindow):
        """Enable SubstructureRedirect on the given window.

        This enables reception of MapRequest and ConfigureRequest events.  At the
        X level, it also enables the reception of CirculateRequest events, but
        those are pretty useless, so we just ignore such events unconditionally
        rather than routing them anywhere.  (The circulate request appears to be
        in the protocol just so simple window managers have an easy way to
        implement the equivalent of alt-tab; I can't imagine how it'd be useful
        these days.  Metacity and KWin do not support it; GTK+/GDK and Qt4 provide
        no way to actually send it.)"""
        self.context_check("substructureRedirect")
        self.addXSelectInput(xwindow, SubstructureRedirectMask)

    def selectFocusChange(self, Window xwindow):
        self.context_check("selectFocusChange")
        self.addXSelectInput(xwindow, FocusChangeMask)


    def XGetWindowProperty(self, Window xwindow, property, req_type=None, int buffer_size=64*1024, delete=False, incr=False):
        # NB: Accepts req_type == 0 for AnyPropertyType
        # "64k is enough for anybody"
        # (Except, I've found window icons that are strictly larger)
        self.context_check("XGetWindowProperty")
        cdef Atom xactual_type = <Atom> 0
        cdef int actual_format = 0
        cdef unsigned long nitems = 0, bytes_after = 0
        cdef unsigned char * prop = <unsigned char*> 0
        cdef Atom xreq_type = AnyPropertyType
        if req_type:
            xreq_type = self.xatom(req_type)
        # This is the most bloody awful API I have ever seen.  You will probably
        # not be able to understand this code fully without reading
        # XGetWindowProperty's man page at least 3 times, slowly.
        cdef Status status = XGetWindowProperty(self.display,
                                                xwindow,
                                                self.xatom(property),
                                                0,
                                                # This argument has to be divided by 4.  Thus
                                                # speaks the spec.
                                                buffer_size // 4,
                                                delete,
                                                xreq_type, &xactual_type,
                                                &actual_format, &nitems, &bytes_after, &prop)
        if status != Success:
            raise PropertyError("no such window")
        if xactual_type == XNone:
            return None
        if xreq_type and xreq_type != xactual_type:
            raise BadPropertyType("expected %s but got %s" % (req_type, self.XGetAtomName(xactual_type)))
        # This should only occur for bad property types:
        assert not (bytes_after and not nitems)
        if bytes_after and not incr:
            raise PropertyOverflow("reserved %i bytes for %s buffer, but data is bigger by %i bytes!" % (buffer_size, req_type, bytes_after))
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
        cdef int nbytes = bytes_per_item * nitems
        data = (<char *> prop)[:nbytes]
        XFree(prop)
        return data


    def GetWindowPropertyType(self, Window xwindow, property, incr=False):
        #as above, but for any property type
        #and returns the type found
        self.context_check("GetWindowPropertyType")
        cdef int buffer_size = 64 * 1024
        cdef Atom xactual_type = <Atom> 0
        cdef int actual_format = 0
        cdef unsigned long nitems = 0, bytes_after = 0
        cdef unsigned char * prop = <unsigned char*> 0
        cdef Status status
        cdef Atom xreq_type = AnyPropertyType
        status = XGetWindowProperty(self.display,
                                     xwindow,
                                     self.xatom(property),
                                     0,
                                     # This argument has to be divided by 4.  Thus
                                     # speaks the spec.
                                     buffer_size // 4,
                                     False,
                                     xreq_type, &xactual_type,
                                     &actual_format, &nitems, &bytes_after, &prop)
        if status != Success:
            raise XError("XGetWindowProperty status: %s" % status)
        if xactual_type == XNone:
            raise BadPropertyType("None type")
        # This should only occur for bad property types:
        assert not (bytes_after and not nitems)
        if bytes_after and not incr:
            raise BadPropertyType("incomplete data: %i bytes after" % bytes_after)
        assert actual_format in (8, 16, 32)
        XFree(prop)
        return self.XGetAtomName(xactual_type), actual_format


    def XDeleteProperty(self, Window xwindow, property):
        self.context_check("XDeleteProperty")
        XDeleteProperty(self.display, xwindow, self.xatom(property))

    def XChangeProperty(self, Window xwindow, property, dtype, int dformat, data):
        "Set a property on a window."
        self.context_check("XChangeProperty")
        assert dformat in (8, 16, 32), "invalid format for property: %s" % dformat
        cdef unsigned char nbytes = dformat//8
        if dformat==32:
            nbytes = sizeof(long)
        assert len(data) % nbytes == 0, "size of data is not a multiple of %s" % nbytes
        cdef int nitems = len(data) // nbytes
        cdef char * data_str = data
        XChangeProperty(self.display, xwindow,
                        self.xatom(property),
                        self.xatom(dtype),
                        dformat,
                        PropModeReplace,
                        <unsigned char *>data_str,
                        nitems)


    # Save set handling
    def XAddToSaveSet(self, Window xwindow):
        self.context_check("XAddToSaveSet")
        XAddToSaveSet(self.display, xwindow)

    def XRemoveFromSaveSet(self, Window xwindow):
        self.context_check("XRemoveFromSaveSet")
        XRemoveFromSaveSet(self.display, xwindow)


    def setClassHint(self, Window xwindow, wmclass, wmname):
        self.context_check("setClassHint")
        cdef XClassHint *classhints = XAllocClassHint()
        assert classhints!=NULL
        classhints.res_class = wmclass
        classhints.res_name = wmname
        XSetClassHint(self.display, xwindow, classhints)
        XFree(classhints)

    def getClassHint(self, Window xwindow) -> Optional[Tuple[str,str]]:
        self.context_check("getClassHint")
        cdef XClassHint *classhints = XAllocClassHint()
        assert classhints!=NULL
        cdef Status s = XGetClassHint(self.display, xwindow, classhints)
        if not s:
            return None
        _name = ""
        _class = ""
        if classhints.res_name!=NULL:
            _name = classhints.res_name[:]
        if classhints.res_class!=NULL:
            _class = classhints.res_class[:]
        XFree(classhints)
        log("XGetClassHint(%#x) classhints: %s, %s", xwindow, _name, _class)
        return (_name, _class)

    def getGeometry(self, Drawable d) -> Tuple[int,int,int,int,int,int]:
        self.context_check("getGeometry")
        cdef Window root_return
        cdef int x, y                                           #@pydev dupe
        cdef unsigned int width, height, border_width, depth    #@pydev dupe
        if not XGetGeometry(self.display, d, &root_return,
                        &x, &y, &width, &height, &border_width, &depth):
            return None
        return x, y, width, height, border_width, depth

    def getParent(self, Window xwindow) -> XID:
        self.context_check("getParent")
        cdef Window root = 0, parent = 0
        cdef Window *children = NULL
        cdef unsigned int nchildren = 0
        if not XQueryTree(self.display, xwindow, &root, &parent, &children, &nchildren):
            return 0
        if nchildren > 0 and children != NULL:
            XFree(children)
        if parent == XNone:
            return 0
        return int(parent)

    def get_children(self, Window xwindow):
        cdef Window root = 0, parent = 0
        cdef Window * children = <Window *> 0
        cdef unsigned int i, nchildren = 0
        if not XQueryTree(self.display, xwindow, &root, &parent, &children, &nchildren):
            return (None, [])
        cdef object pychildren = []
        for i in range(nchildren):
            if children[i]>0:
                pychildren.append(children[i])
        # Apparently XQueryTree sometimes returns garbage in the 'children'
        # pointer when 'nchildren' is 0, which then leads to a segfault when we
        # try to XFree the non-NULL garbage.
        if nchildren > 0 and children != NULL:
            XFree(children)
        return pychildren


    def getSizeHints(self, Window xwindow) -> Dict[str,Any]:
        self.context_check("getSizeHints")
        cdef XSizeHints *size_hints = XAllocSizeHints()
        cdef long supplied_return   #ignored!
        assert size_hints!=NULL
        if not XGetWMNormalHints(self.display, xwindow, size_hints, &supplied_return):
            XFree(size_hints)
            return None
        hints = {}
        if (size_hints.flags & USPosition) or (size_hints.flags & PPosition):
            hints["position"] = size_hints.x, size_hints.y
        if (size_hints.flags & USSize) or (size_hints.flags & PSize):
            hints["size"] = size_hints.width, size_hints.height
        if size_hints.flags & PMinSize:
            hints["min_size"] = size_hints.min_width, size_hints.min_height
        if size_hints.flags & PMaxSize:
            hints["max_size"] = size_hints.max_width, size_hints.max_height
        if size_hints.flags & PBaseSize:
            hints["base_size"] = size_hints.base_width, size_hints.base_height
        if size_hints.flags & PResizeInc:
            hints["resize_inc"] = size_hints.width_inc, size_hints.height_inc
        if size_hints.flags & PAspect:
            try:
                hints["min_aspect_ratio"] = size_hints.min_aspect.x, size_hints.min_aspect.y
                hints["max_aspect_ratio"] = size_hints.max_aspect.x, size_hints.max_aspect.y
            except ZeroDivisionError:
                pass
        if size_hints.flags & PWinGravity:
            hints["win_gravity"] = size_hints.win_gravity
        XFree(size_hints)
        return hints

    def setSizeHints(self, Window xwindow, hints : Dict[str,Any]):
        self.context_check("setSizeHints")
        cdef XSizeHints *size_hints = XAllocSizeHints()
        assert size_hints!=NULL
        position = hints.get("position")
        if position is not None:
            size_hints.flags |= USPosition | PPosition
            size_hints.x, size_hints.y = position
        size = hints.get("size")
        if size is not None:
            size_hints.flags |= USSize | PSize
            size_hints.width, size_hints.height = size
        min_size = hints.get("min_size")
        if min_size is not None:
            size_hints.flags |= PMinSize
            size_hints.min_width, size_hints.min_height = min_size
        max_size = hints.get("max_size")
        if max_size is not None:
            size_hints.flags |= PMaxSize
            size_hints.max_width, size_hints.max_height = max_size
        base_size = hints.get("base_size")
        if base_size is not None:
            size_hints.flags |= PBaseSize
            size_hints.base_width, size_hints.base_height = base_size
        resize_inc = hints.get("resize_inc")
        if resize_inc is not None:
            size_hints.flags |= PResizeInc
            size_hints.width_inc, size_hints.height_inc = resize_inc
        aspect_ratio = hints.get("aspect-ratio")
        if aspect_ratio is not None:
            size_hints.flags |= PAspect
            size_hints.min_aspect.x, size_hints.min_aspect.y = aspect_ratio
        win_gravity = hints.get("win_gravity")
        if win_gravity is not None:
            size_hints.flags |= PWinGravity
            size_hints.win_gravity = win_gravity
        XSetWMNormalHints(self.display, xwindow, size_hints)
        XFree(size_hints)

    def getWMHints(self, Window xwindow) -> Dict[str,Any]:
        self.context_check("getWMHints")
        cdef XWMHints *wm_hints = XGetWMHints(self.display, xwindow)
        if wm_hints==NULL:
            return None
        hints = {}
        if wm_hints.flags & InputHint:
            hints["input"] = wm_hints.input
        if wm_hints.flags & StateHint:
            hints["initial_state"] = wm_hints.initial_state
        if wm_hints.flags & IconPixmapHint:
            hints["icon_pixmap"] = wm_hints.icon_pixmap
        if wm_hints.flags & IconWindowHint:
            hints["icon_window"] = wm_hints.icon_window
        if wm_hints.flags & IconPositionHint:
            hints["icon_position"] = wm_hints.icon_x, wm_hints.icon_y
        if wm_hints.flags & IconMaskHint:
            hints["icon_mask"] = wm_hints.icon_mask
        if wm_hints.flags & WindowGroupHint:
            hints["window_group"] = wm_hints.window_group
        if wm_hints.flags & XUrgencyHint:
            hints["urgency"] = True
        XFree(wm_hints)
        return hints

    def XGetWMProtocols(self, Window xwindow) -> List[str]:
        self.context_check("XGetWMProtocols")
        cdef Atom *protocols_return
        cdef int count_return
        cdef int i = 0
        protocols = []
        if XGetWMProtocols(self.display, xwindow, &protocols_return, &count_return):
            while i<count_return:
                protocol = self.XGetAtomName(protocols_return[i])
                protocols.append(protocol.decode("latin1"))
                i += 1
        return protocols


    def pointer_grab(self, Window xwindow) -> bool:
        self.context_check("pointer_grab")
        cdef Cursor cursor = 0
        cdef unsigned int event_mask = PointerMotionMask
        cdef int r = XGrabPointer(self.display, xwindow, True,
                                  event_mask, GrabModeAsync, GrabModeAsync,
                                  xwindow, cursor, CurrentTime)
        return r==0


    def get_server_time(self, Window xwindow) -> int:
        cdef unsigned char c = b"a"
        cdef Atom timestamp_prop = self.xatom("XPRA_TIMESTAMP_PROP")
        XChangeProperty(self.display, xwindow, timestamp_prop,
                   timestamp_prop,
                   8, PropModeReplace, &c, 1)
        cdef XEvent xevent
        cdef xifevent_timestamp et
        et.window = xwindow
        et.atom = timestamp_prop
        XIfEvent(self.display, &xevent, <void*> &timestamp_predicate, <XPointer> &et)
        return xevent.xproperty.time


ctypedef struct xifevent_timestamp:
    Window window
    Atom atom

cdef Bool timestamp_predicate(Display *display, XEvent  *xevent, XPointer arg) nogil:
    cdef xifevent_timestamp *et = <xifevent_timestamp*> arg
    cdef Window xwindow = <Window> arg
    if xevent.type!=PropertyNotify:
        return False
    return xevent.xproperty.window==et.window and xevent.xproperty.atom==et.atom
