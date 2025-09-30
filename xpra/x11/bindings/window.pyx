# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import cython
from typing import Any, Optional, Tuple, List, Dict
from xpra.x11.error import XError

from xpra.x11.bindings.xlib cimport (
    Display, Drawable, Visual, Window, Bool, XID, Status, Atom, Time, CurrentTime, Cursor, XPointer,
    XVisualInfo,
    XGetVisualInfo, VisualIDMask, XDefaultVisual,
    GrabModeAsync, XGrabPointer,
    Expose,
    XEvent,
    XWMHints, XSizeHints,
    XCreateWindow, XDestroyWindow, XIfEvent, PropertyNotify,
    XSetWindowAttributes,
    XWindowAttributes, XWindowChanges,
    XDefaultRootWindow,
    XFree,
    XGetSelectionOwner, XSetSelectionOwner, XConvertSelection,
    XMapWindow, XMapRaised, XUnmapWindow, XWithdrawWindow, XReparentWindow, XIconifyWindow, XRaiseWindow,
    NextRequest, XSendEvent, XSelectInput,
    XGetWindowAttributes, XGetWindowProperty, XDeleteProperty, XChangeProperty,
    XGetWMNormalHints, XSetWMNormalHints, XGetWMHints, XGetWMProtocols,
    XGetGeometry, XTranslateCoordinates, XConfigureWindow,
    XMoveResizeWindow, XMoveWindow, XResizeWindow,
    XGetInputFocus, XSetInputFocus,
    XAllocSizeHints,
    XAllocIconSize, XIconSize, XSetIconSizes,
    XQueryTree,
    XKillClient,
)
from xpra.x11.bindings.core cimport X11CoreBindingsInstance, import_check
from xpra.x11.bindings.core import constants
from libc.stdint cimport uintptr_t
from libc.string cimport memset

from xpra.log import Logger

import_check("window")

log = Logger("x11", "bindings", "window")

###################################
# Headers, python magic
###################################

######
# Xlib primitives and constants
######

DEF XNone = 0

DEF isUnmapped = 0

DEF screen_number = 0

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

    int CWOverrideRedirect
    int CWEventMask
    int CWBorderWidth

    int NoEventMask
    int PointerMotionMask
    int PointerMotionHintMask
    int ButtonMotionMask
    int StructureNotifyMask
    int SubstructureNotifyMask
    int SubstructureRedirectMask
    int FocusChangeMask
    int PropertyChangeMask

    int AnyPropertyType
    int Success
    int PropModeReplace
    int USPosition
    int PPosition
    int USSize
    int PSize
    int PMinSize
    int IsUnmapped
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


MASKS: Dict[int, str] = {}
for name, constant in constants.items():
    if name.endswith("Mask") and constant>0:
        MASKS[constant] = name[:-4]


def get_mask_strs(int mask) -> list[str]:
    masks = []
    for constant, name in MASKS.items():
        if mask & constant:
            masks.append(name)
    return masks


cdef inline long cast_to_long(Atom i) noexcept nogil:
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


cdef int CONFIGURE_GEOMETRY_MASK = CWX | CWY | CWWidth | CWHeight


cdef class X11WindowBindingsInstance(X11CoreBindingsInstance):

    def __repr__(self):
        return "X11WindowBindings(%s)" % self.display_name

    def get_root_size(self) -> Tuple[int, int]:
        self.context_check("get_root_size")
        cdef int root = self.get_root_xid()
        geom = self.getGeometry(root)
        if not geom:
            raise RuntimeError("failed to query the size of the root window!")
        return int(geom[2]), int(geom[3])

    def get_all_x11_windows(self) -> List[Window]:
        cdef Window root = XDefaultRootWindow(self.display);
        return self.get_all_children(root)

    def get_all_children(self, Window xid) -> List[Window]:
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

    def get_absolute_position(self, Window xid) -> Tuple[int, int]:
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

    def MapWindow(self, Window xwindow) -> None:
        self.context_check("MapWindow")
        XMapWindow(self.display, xwindow)

    def MapRaised(self, Window xwindow) -> None:
        self.context_check("MapRaised")
        XMapRaised(self.display, xwindow)

    def Withdraw(self, Window xwindow) -> None:
        self.context_check("Withdraw")
        return XWithdrawWindow(self.display, xwindow, screen_number)

    def Reparent(self, Window xwindow, Window xparent, int x, int y) -> None:
        self.context_check("Reparent")
        XReparentWindow(self.display, xwindow, xparent, x, y)

    def Iconify(self, Window xwindow) -> None:
        self.context_check("Iconify")
        return XIconifyWindow(self.display, xwindow, screen_number)

    ###################################
    # XUnmapWindow
    ###################################
    def Unmap(self, Window xwindow) -> cython.ulong:
        self.context_check("Unmap")
        cdef unsigned long serial = NextRequest(self.display)
        XUnmapWindow(self.display, xwindow)
        return serial

    def getWindowAttributes(self, Window xwindow) -> Dict[str, Any]:
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
                "map-entries"   : attrs.visual.map_entries,
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
            "your-event-mask"   : attrs.your_event_mask,
            "do-not-propagate-mask" : attrs.do_not_propagate_mask,
            "override-redirect"     : attrs.override_redirect,
        }

    def getEventMask(self, Window xwindow) -> cython.ulong:
        self.context_check("getEventMask")
        cdef XWindowAttributes attrs
        cdef Status status = XGetWindowAttributes(self.display, xwindow, &attrs)
        if status==0:
            return 0
        return attrs.your_event_mask;

    def setEventMask(self, Window xwindow, int mask) -> None:
        self.context_check("setEventMask")
        XSelectInput(self.display, xwindow, mask)

    # Mapped status
    def is_mapped(self, Window xwindow) -> bool:
        return self.get_map_state(xwindow) != IsUnmapped

    def get_map_state(self, Window xwindow) -> int:
        self.context_check("get_map_state")
        cdef XWindowAttributes attrs
        cdef Status status = XGetWindowAttributes(self.display, xwindow, &attrs)
        if status==0:
            return isUnmapped
        return attrs.map_state

    # Override-redirect status
    def is_override_redirect(self, Window xwindow) -> bool:
        self.context_check("is_override_redirect")
        cdef XWindowAttributes or_attrs
        cdef Status status = XGetWindowAttributes(self.display, xwindow, &or_attrs)
        if status==0:
            return False
        return bool(or_attrs.override_redirect)

    # Mapped status
    def is_inputonly(self, Window xwindow) -> bool:
        self.context_check("is_inputonly")
        cdef XWindowAttributes attrs
        cdef Status status = XGetWindowAttributes(self.display, xwindow, &attrs)
        if status==0:
            return False
        return bool(attrs._class==InputOnly)


    def geometry_with_border(self, Window xwindow) -> Tuple[int, int, int, int, int] | None:
        self.context_check("geometry_with_border")
        cdef XWindowAttributes geom_attrs
        cdef Status status = XGetWindowAttributes(self.display, xwindow, &geom_attrs)
        if status==0:
            return None
        return (geom_attrs.x, geom_attrs.y, geom_attrs.width, geom_attrs.height, geom_attrs.border_width)

    def get_depth(self, Drawable d) -> int:
        self.context_check("get_depth")
        cdef Window root
        cdef int x, y
        cdef unsigned int width, height, border_width, depth
        if not XGetGeometry(self.display, d, &root,
                            &x, &y, &width, &height, &border_width, &depth):
            return 0
        return depth

    # Focus management
    def XSetInputFocus(self, Window xwindow, Time time=CurrentTime) -> None:
        self.context_check("XSetInputFocus")
        # Always does RevertToParent
        XSetInputFocus(self.display, xwindow, RevertToParent, time)

    def XGetInputFocus(self) -> Tuple[int, int]:
        #context check not needed!
        cdef Window w = 0
        cdef int revert_to = 0
        XGetInputFocus(self.display, &w, &revert_to)
        return int(w), int(revert_to)

    def XRaiseWindow(self, Window window) -> None:
        self.context_check("XRaiseWindow")
        XRaiseWindow(self.display, window)

    ###################################
    # XKillClient
    ###################################
    def XKillClient(self, Window xwindow) -> int:
        self.context_check("XKillClient")
        return XKillClient(self.display, xwindow)

    ###################################
    # Smarter convenience wrappers
    ###################################

    def XGetSelectionOwner(self, atom) -> Window:
        self.context_check("XGetSelectionOwner")
        return XGetSelectionOwner(self.display, self.str_to_atom(atom))

    def XSetSelectionOwner(self, Window xwindow, atom, Time time=CurrentTime):
        self.context_check("XSetSelectionOwner")
        return XSetSelectionOwner(self.display, self.str_to_atom(atom), xwindow, time)

    def sendClientMessage(self, Window xtarget, Window xwindow, int propagate, int event_mask,
                          message_type, data0=0, data1=0, data2=0, data3=0, data4=0) -> None:
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
        e.xclient.message_type = self.str_to_atom(message_type)
        e.xclient.format = 32
        e.xclient.data.l[0] = cast_to_long(self.xatom(data0))
        e.xclient.data.l[1] = cast_to_long(self.xatom(data1))
        e.xclient.data.l[2] = cast_to_long(self.xatom(data2))
        e.xclient.data.l[3] = cast_to_long(self.xatom(data3))
        e.xclient.data.l[4] = cast_to_long(self.xatom(data4))
        cdef Status s = XSendEvent(self.display, xtarget, propagate, event_mask, &e)
        if s == 0:
            raise ValueError("failed to serialize ClientMessage")

    def sendClick(self, Window xtarget, int button, onoff, int x_root, int y_root, int x, int y) -> None:
        self.context_check("sendClick")
        cdef Window r = XDefaultRootWindow(self.display)
        log("sending message to %#x", xtarget)
        cdef XEvent e
        e.type = ButtonPress
        e.xany.display = self.display
        e.xany.window = xtarget
        #e.xclient.message_type = self.str_to_atom(message_type)
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

    def send_xembed_message(self, Window xwindow, opcode, detail, data1, data2) -> None:
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
        e.xclient.message_type = self.str_to_atom("_XEMBED")
        e.xclient.format = 32
        e.xclient.data.l[0] = CurrentTime
        e.xclient.data.l[1] = opcode
        e.xclient.data.l[2] = detail
        e.xclient.data.l[3] = data1
        e.xclient.data.l[4] = data2
        s = XSendEvent(self.display, xwindow, False, NoEventMask, &e)
        if s == 0:
            raise ValueError("failed to serialize XEmbed Message")

    def send_expose(self, Window xwindow, int x, int y, int width, int height, int count=0) -> None:
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
    def selectSelectionInput(self, Window xwindow) -> None:
        self.context_check("selectSelectionInput")
        self.addXSelectInput(xwindow, SelectionNotify)

    def sendSelectionNotify(self, Window xwindow, selection, target, property, Time time=CurrentTime) -> None:
        self.context_check("sendSelectionNotify")
        cdef XEvent e
        e.type = SelectionNotify
        e.xselection.requestor = xwindow
        e.xselection.selection = self.str_to_atom(selection)
        e.xselection.target = self.str_to_atom(target)
        e.xselection.time = time
        if property:
            e.xselection.property = self.str_to_atom(property)
        else:
            e.xselection.property = 0
        cdef Status s = XSendEvent(self.display, xwindow, True, 0, &e)
        if s == 0:
            raise ValueError("failed to serialize SelectionNotify")

    def ConvertSelection(self, selection, target, property, Window requestor, Time time=CurrentTime) -> int:
        self.context_check("ConvertSelection")
        return XConvertSelection(self.display, self.str_to_atom(selection), self.str_to_atom(target),
                                 self.str_to_atom(property), requestor, time)

    def sendConfigureNotify(self, Window xwindow) -> None:
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

    def CreateCorralWindow(self, Window parent, Window xid, int x, int y) -> Window:
        self.context_check("CreateCorralWindow")
        # copy the dimensions from the window we will wrap:
        cdef int ox, oy
        cdef Window root
        cdef unsigned int width, height, border_width, depth
        if not XGetGeometry(self.display, xid, &root,
                        &ox, &oy, &width, &height, &border_width, &depth):
            return 0
        cdef long event_mask = PropertyChangeMask | StructureNotifyMask | SubstructureNotifyMask
        return self.CreateWindow(parent, x, y, width, height, OR=False, event_mask=event_mask)

    def CreateWindow(self, Window parent, int x=0, int y=0, int width=1, int height=1,
                           depth=0, int OR=0, long event_mask=0,
                           int inputoutput=InputOutput, unsigned long visualid=0) -> Window:
        self.context_check("CreateWindow")
        cdef XSetWindowAttributes attributes
        memset(<void*> &attributes, 0, sizeof(XSetWindowAttributes))
        attributes.event_mask = event_mask
        cdef unsigned long valuemask = CWEventMask
        if OR:
            valuemask |= CWOverrideRedirect
            attributes.override_redirect = 1
        cdef Visual* visual = <Visual*> CopyFromParent
        if inputoutput != InputOnly:
            if depth == 0:
                depth = self.get_depth(parent)
            if visualid:
                visual = self.get_visual(visualid)
        return XCreateWindow(self.display, parent,
                             x, y, width, height, 0, depth,
                             inputoutput, visual,
                             valuemask, &attributes)

    cdef Visual* get_visual(self, int visualid) noexcept:
        cdef Visual* visual = NULL
        cdef int count
        cdef XVisualInfo vinfo_template
        vinfo_template.visualid = visualid
        cdef XVisualInfo *vinfo = XGetVisualInfo(self.display, VisualIDMask, &vinfo_template, &count)
        if count != 1 or vinfo == NULL:
            log.error("Error: visual %i not found, count=%i, vinfo=%#x", visualid, count, <uintptr_t> vinfo)
        else:
            visual = vinfo[0].visual
        if vinfo:
            XFree(vinfo)
        return visual

    def get_default_visualid(self) -> int:
        cdef Visual *visual = XDefaultVisual(self.display, 0)
        if not visual:
            return 0
        return visual.visualid

    def get_rgba_visualid(self, depth=32) -> int:
        cdef XVisualInfo vinfo_template
        cdef int count
        cdef XVisualInfo *vinfo = XGetVisualInfo(self.display, 0, &vinfo_template, &count)
        if not count or vinfo == NULL:
            log.error("Error: no visuals found, count=%i, vinfo=%#x", count, <uintptr_t> vinfo)
            if vinfo:
                XFree(vinfo)
            return 0
        cdef unsigned long visualid = 0
        for i in range(count):
            if vinfo[i].depth != depth:
                continue
            # check rgb mask:
            if vinfo[i].red_mask != 0xff0000 or vinfo[i].green_mask != 0x00ff00 or vinfo[i].blue_mask != 0x0000ff:
                continue
            visualid = vinfo[i].visualid
            break
        XFree(vinfo)
        return visualid

    def DestroyWindow(self, Window w) -> None:
        self.context_check("DestroyWindow")
        return XDestroyWindow(self.display, w)

    def ConfigureWindow(self, Window xwindow,
                        int x, int y, int width, int height, int border=0,
                        int sibling=0, int stack_mode=0,
                        int value_mask=CONFIGURE_GEOMETRY_MASK) -> None:
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

    def configure(self, Window xwindow, x, y, width, height, fields=None) -> None:
        # Reconfigure the window.  We have to use XConfigureWindow directly
        # instead of GdkWindow.resize, because GDK does not give us any way to
        # squash the border.

        # The caller can pass an XConfigureWindow-style fields mask to turn off
        # some of these bits; this is useful if they are pulling such a field out
        # of a ConfigureRequest (along with the other arguments they are passing
        # to us).  This also means we need to be careful to zero out any bits
        # besides these, because they could be set to anything.
        self.context_check("configure")
        cdef int geom_flags = CWX | CWY | CWWidth | CWHeight
        if fields is None:
            fields = geom_flags
        else:
            fields = fields & geom_flags
        # But we always unconditionally squash the border to zero.
        fields = fields | CWBorderWidth
        self.ConfigureWindow(xwindow, x, y, width, height, value_mask=fields)

    def MoveResizeWindow(self, Window xwindow, int x, int y, int width, int height) -> bool:
        self.context_check("MoveResizeWindow")
        return bool(XMoveResizeWindow(self.display, xwindow, x, y, width, height))

    def ResizeWindow(self, Window xwindow, int width, int height) -> bool:
        self.context_check("ResizeWindow")
        return bool(XResizeWindow(self.display, xwindow, width, height))

    def MoveWindow(self, Window xwindow, int x, int y) -> bool:
        self.context_check("MoveWindow")
        return bool(XMoveWindow(self.display, xwindow, x, y))

    def get_event_mask_strs(self, Window xwindow) -> Sequence[str]:
        self.context_check("get_event_mask_strs")
        cdef XWindowAttributes curr
        XGetWindowAttributes(self.display, xwindow, &curr)
        return get_mask_strs(curr.your_event_mask)

    def addDefaultEvents(self, Window xwindow) -> None:
        self.context_check("addDefaultEvents")
        ADDMASK = StructureNotifyMask | PropertyChangeMask | FocusChangeMask | PointerMotionMask | PointerMotionHintMask | ButtonMotionMask
        self.addXSelectInput(xwindow, ADDMASK)

    def addXSelectInput(self, Window xwindow, long add_mask) -> None:
        self.context_check("addXSelectInput")
        cdef XWindowAttributes curr
        XGetWindowAttributes(self.display, xwindow, &curr)
        cdef long mask = curr.your_event_mask | add_mask
        XSelectInput(self.display, xwindow, mask)

    def substructureRedirect(self, Window xwindow) -> None:
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

    def selectFocusChange(self, Window xwindow) -> None:
        self.context_check("selectFocusChange")
        self.addXSelectInput(xwindow, FocusChangeMask)

    def XGetWindowProperty(self, Window xwindow, property, req_type="",
                           int buffer_size=64*1024, delete=False, incr=False) -> bytes:
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
            xreq_type = self.str_to_atom(req_type)
        # This is the most bloody awful API I have ever seen.  You will probably
        # not be able to understand this code fully without reading
        # XGetWindowProperty's man page at least 3 times, slowly.
        cdef Status status = XGetWindowProperty(self.display,
                                                xwindow,
                                                self.str_to_atom(property),
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
            raise BadPropertyType("expected %s but got %s" % (req_type, self.get_atom_name(xactual_type)))
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

    def GetWindowPropertyType(self, Window xwindow, property, incr=False) -> Tuple[str, int]:
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
                                     self.str_to_atom(property),
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
        return self.get_atom_name(xactual_type), actual_format

    def XDeleteProperty(self, Window xwindow, property) -> None:
        self.context_check("XDeleteProperty")
        XDeleteProperty(self.display, xwindow, self.str_to_atom(property))

    def XChangeProperty(self, Window xwindow, property, dtype, int dformat, data) -> None:
        "Set a property on a window."
        self.context_check("XChangeProperty")
        if dformat not in (8, 16, 32):
            raise ValueError(f"invalid format for property {property}: {dformat}")
        cdef unsigned char nbytes = dformat//8
        if dformat==32:
            nbytes = sizeof(long)
        assert len(data) % nbytes == 0, "size of data is not a multiple of %s" % nbytes
        cdef int nitems = len(data) // nbytes
        cdef char * data_str = data
        XChangeProperty(self.display, xwindow,
                        self.str_to_atom(property),
                        self.str_to_atom(dtype),
                        dformat,
                        PropModeReplace,
                        <unsigned char *>data_str,
                        nitems)

    def setRootIconSizes(self, int w, int h) -> None:
        cdef Window root = XDefaultRootWindow(self.display);
        cdef XIconSize *icon_size = XAllocIconSize()
        assert icon_size
        icon_size.min_width = w
        icon_size.max_width = w
        icon_size.width_inc = 0
        icon_size.min_height = h
        icon_size.max_height = h
        icon_size.height_inc = 0
        XSetIconSizes(self.display, root, icon_size, 1)
        XFree(icon_size)

    def getGeometry(self, Drawable d) -> Tuple[int, int, int, int, int, int]:
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

    def get_children(self, Window xwindow) -> List[Window]:
        cdef Window root = 0, parent = 0
        cdef Window * children = <Window *> 0
        cdef unsigned int i, nchildren = 0
        if not XQueryTree(self.display, xwindow, &root, &parent, &children, &nchildren):
            return []
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
            return {}
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

    def setSizeHints(self, Window xwindow, hints : Dict[str,Any]) -> None:
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
        log("getWMHints(%x)=%s", xwindow, hints)
        XFree(wm_hints)
        return hints

    def XGetWMProtocols(self, Window xwindow) -> Tuple[str]:
        self.context_check("XGetWMProtocols")
        cdef Atom *protocols_return
        cdef int count_return
        cdef int i = 0
        protocols = []
        if XGetWMProtocols(self.display, xwindow, &protocols_return, &count_return):
            while i<count_return:
                protocols.append(self.get_atom_name(protocols_return[i]))
                i += 1
        return tuple(protocols)

    def pointer_grab(self, Window xwindow) -> bool:
        self.context_check("pointer_grab")
        cdef Cursor cursor = 0
        cdef unsigned int event_mask = PointerMotionMask
        cdef int r = XGrabPointer(self.display, xwindow, True,
                                  event_mask, GrabModeAsync, GrabModeAsync,
                                  xwindow, cursor, CurrentTime)
        return r == 0

    def get_server_time(self, Window xwindow) -> cython.ulong:
        cdef unsigned char c = b"a"
        cdef Atom timestamp_prop = self.str_to_atom("XPRA_TIMESTAMP_PROP")
        XChangeProperty(self.display, xwindow, timestamp_prop,
                   timestamp_prop,
                   8, PropModeReplace, &c, 1)
        cdef XEvent xevent
        cdef xifevent_timestamp et
        et.window = xwindow
        et.atom = timestamp_prop
        XIfEvent(self.display, &xevent, <void*> &timestamp_predicate, <XPointer> &et)
        XDeleteProperty(self.display, xwindow, timestamp_prop)
        return xevent.xproperty.time


ctypedef struct xifevent_timestamp:
    Window window
    Atom atom


cdef Bool timestamp_predicate(Display *display, XEvent  *xevent, XPointer arg)  noexcept nogil:
    cdef xifevent_timestamp *et = <xifevent_timestamp*> arg
    cdef Window xwindow = <Window> arg
    if xevent.type!=PropertyNotify:
        return False
    return xevent.xproperty.window==et.window and xevent.xproperty.atom==et.atom


cdef X11WindowBindingsInstance singleton = None


def X11WindowBindings() -> X11WindowBindingsInstance:
    global singleton
    if singleton is None:
        singleton = X11WindowBindingsInstance()
    return singleton
