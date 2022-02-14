# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


ctypedef unsigned long CARD32
ctypedef int Bool
ctypedef int Status
ctypedef CARD32 Atom
ctypedef CARD32 XID
ctypedef char* XPointer
ctypedef XID Drawable
ctypedef XID Window
ctypedef XID Pixmap
ctypedef CARD32 Colormap
ctypedef CARD32 VisualID
ctypedef CARD32 Time
ctypedef XID KeySym

cdef extern from "X11/X.h":
    unsigned long NoSymbol

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
    int XUngrabPointer(Display * display, Time t)

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
        int c_class
        unsigned long red_mask
        unsigned long green_mask
        unsigned long blue_mask
        int colormap_size
        int bits_per_rgb

    ctypedef struct XColor:
        unsigned long pixel                 # pixel value
        unsigned short red, green, blue     # rgb values
        char flags                          # DoRed, DoGreen, DoBlue

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

    ctypedef struct XRectangle:
        short x, y
        unsigned short width, height

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

    # events:
    Status XSendEvent(Display *, Window target, Bool propagate,
                      unsigned long event_mask, XEvent * event)

    int XSelectInput(Display * display, Window w, unsigned long event_mask)

    # properties:
    int XChangeProperty(Display *, Window w, Atom property,
         Atom type, int format, int mode, unsigned char * data, int nelements)
    int XGetWindowProperty(Display * display, Window w, Atom property,
         long offset, long length, Bool delete,
         Atom req_type, Atom * actual_type,
         int * actual_format,
         unsigned long * nitems, unsigned long * bytes_after,
         unsigned char ** prop)
    int XDeleteProperty(Display * display, Window w, Atom property)

    int XAddToSaveSet(Display *, Window w)
    int XRemoveFromSaveSet(Display *, Window w)

    # windows:
    Status XGetWindowAttributes(Display * display, Window w,
                                XWindowAttributes * attributes)

    int XConfigureWindow(Display * display, Window w,
         unsigned int value_mask, XWindowChanges * changes)
    Status XReconfigureWMWindow(Display * display, Window w, int screen_number,
                                unsigned int value_mask, XWindowChanges *values)
    int XMoveResizeWindow(Display * display, Window w, int x, int y, int width, int height)

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
    int XConvertSelection(Display * display, Atom selection, Atom target, Atom property, Window requestor, Time time)

    # events:
    # There are way more event types than this; add them as needed.
    ctypedef struct XAnyEvent:
        int type
        unsigned long serial
        Bool send_event
        Display * display
        Window window
    ctypedef struct XConfigureEvent:
        Window event    # Same as xany.window, confusingly.
                        # The selected-on window.
        Window window   # The effected window.
        int x, y, width, height, border_width
        Window above
        Bool override_redirect
    # Needed to broadcast that we are a window manager, among other things:
    union payload_for_XClientMessageEvent:
        char b[20]
        short s[10]
        unsigned long l[5]
    ctypedef struct XClientMessageEvent:
        Atom message_type
        int format
        payload_for_XClientMessageEvent data
    ctypedef struct XButtonEvent:
        Window root
        Window subwindow
        Time time
        int x, y                # pointer x, y coordinates in event window
        int x_root, y_root      # coordinates relative to root */
        unsigned int state      # key or button mask
        unsigned int button
        Bool same_screen
    ctypedef struct XSelectionEvent:
        Window requestor
        Atom selection
        Atom target
        Atom property
        Time time
    # The only way we can learn about override redirects is through MapNotify,
    # which means we need to be able to get MapNotify for windows we have
    # never seen before, which means we can't rely on GDK:
    ctypedef union XEvent:
        int type
        XAnyEvent xany
        XButtonEvent xbutton
        XConfigureEvent xconfigure
        XClientMessageEvent xclient
        XSelectionEvent xselection
