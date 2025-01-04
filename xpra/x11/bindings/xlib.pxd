# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# @ReservedAssignment

ctypedef unsigned char BYTE
ctypedef unsigned char CARD8
ctypedef unsigned short CARD16
ctypedef unsigned long CARD32
ctypedef int BOOL
ctypedef int Bool
ctypedef int Status
ctypedef CARD32 Atom
ctypedef CARD32 XID
ctypedef char* XPointer
ctypedef XID Drawable
ctypedef XID Window
ctypedef XID Pixmap
ctypedef XID Cursor
ctypedef CARD32 Colormap
ctypedef CARD32 VisualID
ctypedef CARD32 Time
ctypedef XID KeySym


cdef extern from "X11/X.h":
    unsigned long NoSymbol
    unsigned long AnyPropertyType
    unsigned int PropModeReplace
    unsigned int PropertyNotify
    unsigned int Expose


cdef extern from "X11/Xutil.h":
    ctypedef struct aspect:
        int x,y
    ctypedef struct XSizeHints:
        long flags                  #marks which fields in this structure are defined
        int x, y                    #Obsolete
        int width, height           #Obsolete
        int min_width, min_height
        int max_width, max_height
        int width_inc, height_inc
        aspect min_aspect, max_aspect
        int base_width, base_height
        int win_gravity
        #this structure may be extended in the future

    ctypedef struct XWMHints:
        long flags                  #marks which fields in this structure are defined
        Bool input                  #does this application rely on the window manager to get keyboard input?
        int initial_state
        Pixmap icon_pixmap          #pixmap to be used as icon
        Window icon_window          #window to be used as icon
        int icon_x, icon_y          #initial position of icon
        Pixmap icon_mask            #pixmap to be used as mask for icon_pixmap
        XID window_group            #id of related window group


cdef extern from "X11/Xlib.h":
    int CurrentTime
    int MappingBusy
    int GrabModeAsync
    int AnyKey
    int AnyModifier

    int VisualIDMask
    #query colors flags:
    int DoRed
    int DoGreen
    int DoBlue

    unsigned long AllPlanes
    int XYPixmap
    int ZPixmap
    int MSBFirst
    int LSBFirst

    int BadRequest
    int Success

    int XIAnyPropertyType

    ctypedef struct Display:
        pass

    Atom XInternAtom(Display * display, char * atom_name, Bool only_if_exists)
    Status XInternAtoms(Display *display, char **names, int count, Bool only_if_exists, Atom *atoms_return)
    char *XGetAtomName(Display *display, Atom atom)

    int XFree(void * data)
    int XKillClient(Display *, XID)

    void XGetErrorText(Display * display, int code, char * buffer_return, int length)

    int XUngrabKeyboard(Display * display, Time t)
    int XGrabPointer(Display *display, Window grab_window, Bool owner_events,
                     unsigned int event_mask, int pointer_mode, int keyboard_mode,
                     Window confine_to, Cursor cursor, Time time)
    int XUngrabPointer(Display *display, Time time)

    int *XSynchronize(Display *display, Bool onoff)

    Display *XOpenDisplay(char *display_name)
    int XCloseDisplay(Display *display)

    ctypedef struct XRectangle:
        short x, y
        unsigned short width, height

    ctypedef struct XClassHint:
        char *res_name
        char *res_class

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

    ctypedef struct Visual:
        void    *ext_data       #XExtData *ext_data;     /* hook for extension to hang data */
        VisualID visualid
        int c_class
        unsigned long red_mask
        unsigned long green_mask
        unsigned long blue_mask
        int bits_per_rgb
        int map_entries

    ctypedef struct XVisualInfo:
        Visual *visual
        VisualID visualid
        int screen
        unsigned int depth
        int c_class "class"
        unsigned long red_mask
        unsigned long green_mask
        unsigned long blue_mask
        int colormap_size
        int bits_per_rgb

    ctypedef struct XColor:
        unsigned long pixel                 # pixel value
        unsigned short red, green, blue     # rgb values
        char flags                          # DoRed, DoGreen, DoBlue

    ctypedef struct XSetWindowAttributes:
        Pixmap background_pixmap            # background, None, or ParentRelative
        unsigned long background_pixel      # background pixel
        Pixmap border_pixmap                # border of the window or CopyFromParent
        unsigned long border_pixel          # border pixel value
        int bit_gravity                     # one of bit gravity values
        int win_gravity                     # one of the window gravity values
        int backing_store                   # NotUseful, WhenMapped, Always
        unsigned long backing_planes        # planes to be preserved if possible
        unsigned long backing_pixel         # value to use in restoring planes
        Bool save_under                     # should bits under be saved? (popups)
        long event_mask                     # set of events that should be saved
        long do_not_propagate_mask          # set of events that should not propagate
        Bool override_redirect              # boolean value for override_redirect
        Colormap colormap                   # color map to be associated with window
        Cursor cursor

    ctypedef struct XWindowChanges:
        int x, y, width, height, border_width
        Window sibling
        int stack_mode

    ctypedef struct XWindowAttributes:
        int x, y, width, height, border_width
        int depth
        Visual *visual
        int _class "class"
        int bit_gravity, win_gravity, backing_store
        unsigned long backing_planes, backing_pixel
        Bool save_under
        Colormap colormap
        Bool map_installed
        int map_state
        long all_event_masks
        long your_event_mask
        long do_not_propagate_mask
        Bool override_redirect
        #Screen *screen

    ctypedef struct XGenericEventCookie:
        int            type     # of event. Always GenericEvent
        unsigned long  serial
        Bool           send_event
        Display        *display
        int            extension    #major opcode of extension that caused the event
        int            evtype       #actual event type
        unsigned int   cookie
        void           *data

    ctypedef unsigned char KeyCode
    ctypedef struct XModifierKeymap:
        int max_keypermod
        KeyCode * modifiermap # an array with 8*max_keypermod elements


    Bool XQueryExtension(Display * display, char *name,
                         int *major_opcode_return, int *first_event_return, int *first_error_return)

    Bool XGetEventData(Display *display, XGenericEventCookie *cookie)
    void XFreeEventData(Display *display, XGenericEventCookie *cookie)

    Window XDefaultRootWindow(Display * display)

    Bool XQueryPointer(Display *display, Window w, Window *root_return, Window *child_return, int *root_x_return, int *root_y_return,
                       int *win_x_return, int *win_y_return, unsigned int *mask_return)
    int XFlush(Display *dpy)
    int XSync(Display *dpy, Bool discard)

    int XConnectionNumber(Display *display)

    int XPending(Display *display)

    # Icon sizes
    ctypedef struct XIconSize:
        int min_width
        int min_height
        int max_width
        int max_height
        int width_inc;
        int height_inc;

    XIconSize *XAllocIconSize()
    int XSetIconSizes(Display *display, Window w, XIconSize* size_list, int count)

    # Keyboard bindings
    XModifierKeymap* XGetModifierMapping(Display* display)
    int XFreeModifiermap(XModifierKeymap* modifiermap)
    int XDisplayKeycodes(Display* display, int* min_keycodes, int* max_keycodes)
    KeySym XStringToKeysym(char* string)
    KeySym* XGetKeyboardMapping(Display* display, KeyCode first_keycode, int keycode_count, int* keysyms_per_keycode_return)
    int XChangeKeyboardMapping(Display* display, int first_keycode, int keysyms_per_keycode, KeySym* keysyms, int num_codes)
    XModifierKeymap* XInsertModifiermapEntry(XModifierKeymap* modifiermap, KeyCode keycode_entry, int modifier)
    char* XKeysymToString(KeySym keysym)

    int XSetModifierMapping(Display* display, XModifierKeymap* modifiermap)

    int XGrabKey(Display * display, int keycode, unsigned int modifiers,
                 Window grab_window, Bool owner_events,
                 int pointer_mode, int keyboard_mode)
    int XUngrabKey(Display * display, int keycode, unsigned int modifiers,
                   Window grab_window)
    int XQueryKeymap(Display * display, char [32] keys_return)

    #Threading:
    Status XInitThreads()

    # error handling:
    ctypedef int (*X11IOERRORHANDLER)(Display *) except 0
    int XSetIOErrorHandler(X11IOERRORHANDLER  handler)
    ctypedef struct XErrorEvent:
        int type
        Display *display
        unsigned long serial
        unsigned char error_code
        unsigned char request_code
        unsigned char minor_code
        XID resourceid
    ctypedef int (*X11ERRORHANDLER)(Display *, XErrorEvent *event) except 0
    int XSetErrorHandler(X11ERRORHANDLER handler)

    # events:
    Status XSendEvent(Display *, Window target, Bool propagate,
                      unsigned long event_mask, XEvent * event)
    void XNextEvent(Display *display, XEvent *event_return) nogil
    int XSelectInput(Display * display, Window w, unsigned long event_mask)

    # properties:
    int XChangeProperty(Display *, Window w, Atom prop,
         Atom ptype, int fmt, int mode, unsigned char * data, int nelements)
    int XGetWindowProperty(Display * display, Window w, Atom prop,
         long offset, long length, Bool delete,
         Atom req_type, Atom * actual_type,
         int * actual_format,
         unsigned long * nitems, unsigned long * bytes_after,
         unsigned char ** prop)
    int XDeleteProperty(Display * display, Window w, Atom prop)

    int XAddToSaveSet(Display *, Window w)
    int XRemoveFromSaveSet(Display *, Window w)

    Visual *XDefaultVisual(Display *display, int screen_number)
    XVisualInfo *XGetVisualInfo(Display *display, long vinfo_mask, XVisualInfo *vinfo_template, int *nitems_return)

    # windows:
    Status XGetWindowAttributes(Display * display, Window w,
                                XWindowAttributes * attributes)

    Window XCreateWindow(Display *display, Window parent,
                         int x, int y, unsigned int width, unsigned int height, unsigned int border_width, int depth,
                         unsigned int _class, Visual *visual,
                         unsigned long valuemask, XSetWindowAttributes *attributes)
    int XDestroyWindow(Display *display, Window w)

    int XConfigureWindow(Display * display, Window w,
         unsigned int value_mask, XWindowChanges * changes)
    Status XReconfigureWMWindow(Display * display, Window w, int screen_number,
                                unsigned int value_mask, XWindowChanges *values)
    int XMoveResizeWindow(Display * display, Window w, int x, int y, int width, int height)
    int XMoveWindow(Display * display, Window w, int x, int y)
    int XResizeWindow(Display * display, Window w, int width, int height)

    Bool XTranslateCoordinates(Display * display,
                               Window src_w, Window dest_w,
                               int src_x, int src_y,
                               int * dest_x, int * dest_y,
                               Window * child)

    Status XQueryTree(Display * display, Window w,
                      Window * root, Window * parent,
                      Window ** children, unsigned int * nchildren)

    # focus:
    int XSetInputFocus(Display * display, Window focus,
                                          int revert_to, Time ctime)
    int XGetInputFocus(Display * display, Window * focus,
                                          int * revert_to)

    # XUnmapWindow
    int XUnmapWindow(Display *, Window)
    unsigned long NextRequest(Display *)

    int XIconifyWindow(Display *, Window, int screen_number)

    # XMapWindow
    int XMapWindow(Display *, Window)
    int XMapRaised(Display *, Window)
    Status XWithdrawWindow(Display *, Window, int screen_number)
    void XReparentWindow(Display *, Window w, Window parent, int x, int y)
    void XRaiseWindow(Display *display, Window w)

    XClassHint *XAllocClassHint()
    Status XGetClassHint(Display *display, Window w, XClassHint *class_hints_return)
    void XSetClassHint(Display *display, Window w, XClassHint *class_hints)

    Status XGetGeometry(Display *display, Drawable d, Window *root_return,
                        int *x_return, int *y_return, unsigned int  *width_return, unsigned int *height_return,
                        unsigned int *border_width_return, unsigned int *depth_return)

    XSizeHints *XAllocSizeHints()
    #Status XGetWMSizeHints(Display *display, Window w, XSizeHints *hints_return, long *supplied_return, Atom property)
    void XSetWMNormalHints(Display *display, Window w, XSizeHints *hints)
    Status XGetWMNormalHints(Display *display, Window w, XSizeHints *hints_return, long *supplied_return)
    XWMHints *XGetWMHints(Display *display, Window w)

    Status XGetWMProtocols(Display *display, Window w, Atom **protocols_return, int *count_return)

    # selection:
    Window XGetSelectionOwner(Display * display, Atom selection)
    int XSetSelectionOwner(Display * display, Atom selection, Window owner, Time ctime)
    int XConvertSelection(Display * display, Atom selection, Atom target, Atom prop,
                          Window requestor, Time time)

    #ctypedef Bool (*XIf_predicate) (Display *display, XEvent *event, XPointer arg) nogil
    int XIfEvent(Display *display, XEvent *event_return, void *predicate, XPointer arg)

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
    ctypedef struct XSelectionRequestEvent:
        Window owner
        Window requestor
        Atom selection
        Atom target
        Atom property
        Time time
    ctypedef struct XSelectionClearEvent:
        Window window
        Atom selection
        Time time
    ctypedef struct XSelectionEvent:
        int subtype
        Window requestor
        Atom selection
        Atom target
        Atom property
        Time time
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
    ctypedef struct XButtonEvent:
        Window root
        Window subwindow
        Time time
        int x, y                # pointer x, y coordinates in event window
        int x_root, y_root      # coordinates relative to root */
        unsigned int state      # key or button mask
        unsigned int button
        Bool same_screen
    ctypedef struct XMapEvent:
        Window window
        Bool override_redirect
    ctypedef struct XUnmapEvent:
        Window window
        Bool from_configure
    ctypedef struct XDestroyWindowEvent:
        Window window
    ctypedef struct XPropertyEvent:
        Window window
        Atom atom
        Time time
    ctypedef struct XKeyEvent:
        unsigned int state
        unsigned int keycode

    ctypedef struct XExposeEvent:
        Window window
        int x, y
        int width, height
        int count

    ctypedef union XEvent:
        int type
        XAnyEvent xany
        XKeyEvent xkey
        XButtonEvent xbutton
        XMapRequestEvent xmaprequest
        XConfigureRequestEvent xconfigurerequest
        XSelectionRequestEvent xselectionrequest
        XSelectionClearEvent xselectionclear
        XResizeRequestEvent xresizerequest
        XCirculateRequestEvent xcirculaterequest
        XConfigureEvent xconfigure
        XCrossingEvent xcrossing
        XFocusChangeEvent xfocus
        XMotionEvent xmotion
        XClientMessageEvent xclient
        XSelectionEvent xselection
        XMapEvent xmap
        XCreateWindowEvent xcreatewindow
        XUnmapEvent xunmap
        XReparentEvent xreparent
        XDestroyWindowEvent xdestroywindow
        XPropertyEvent xproperty
        XGenericEventCookie xcookie
        XExposeEvent xexpose
