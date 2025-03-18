# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct
from select import select
from time import monotonic

from xpra.log import Logger
log = Logger("x11", "bindings", "record")

from xpra.x11.bindings.xlib cimport (
    Display, XID, Window, Status, Time, Cursor,
    BOOL, BYTE, CARD8, CARD16, CARD32,
    XOpenDisplay,
    XFree, XFlush, XSync, XConnectionNumber, XPending,
)
from xpra.x11.bindings.core cimport X11CoreBindingsInstance


ctypedef unsigned long   XRecordClientSpec
ctypedef unsigned long   XRecordContext


cdef extern from "X11/Xproto.h":
    int X_CreateWindow
    int X_ChangeWindowAttributes
    int X_GetWindowAttributes
    int X_DestroyWindow
    int X_DestroySubwindows
    int X_ChangeSaveSet
    int X_ReparentWindow
    int X_MapWindow
    int X_MapSubwindows
    int X_UnmapWindow
    int X_UnmapSubwindows
    int X_ConfigureWindow
    int X_CirculateWindow
    int X_GetGeometry
    int X_QueryTree
    int X_InternAtom
    int X_GetAtomName
    int X_ChangeProperty
    int X_DeleteProperty
    int X_GetProperty
    int X_ListProperties
    int X_SetSelectionOwner
    int X_GetSelectionOwner
    int X_ConvertSelection
    int X_SendEvent
    int X_GrabPointer
    int X_UngrabPointer
    int X_GrabButton
    int X_UngrabButton
    int X_ChangeActivePointerGrab
    int X_GrabKeyboard
    int X_UngrabKeyboard
    int X_GrabKey
    int X_UngrabKey
    int X_AllowEvents
    int X_GrabServer
    int X_UngrabServer
    int X_QueryPointer
    int X_GetMotionEvents
    int X_TranslateCoords
    int X_WarpPointer
    int X_SetInputFocus
    int X_GetInputFocus
    int X_QueryKeymap
    int X_OpenFont
    int X_CloseFont
    int X_QueryFont
    int X_QueryTextExtents
    int X_ListFonts
    int X_ListFontsWithInfo
    int X_SetFontPath
    int X_GetFontPath
    int X_CreatePixmap
    int X_FreePixmap
    int X_CreateGC
    int X_ChangeGC
    int X_CopyGC
    int X_SetDashes
    int X_SetClipRectangles
    int X_FreeGC
    int X_ClearArea
    int X_CopyArea
    int X_CopyPlane
    int X_PolyPoint
    int X_PolyLine
    int X_PolySegment
    int X_PolyRectangle
    int X_PolyArc
    int X_FillPoly
    int X_PolyFillRectangle
    int X_PolyFillArc
    int X_PutImage
    int X_GetImage
    int X_PolyText8
    int X_PolyText16
    int X_ImageText8
    int X_ImageText16
    int X_CreateColormap
    int X_FreeColormap
    int X_CopyColormapAndFree
    int X_InstallColormap
    int X_UninstallColormap
    int X_ListInstalledColormaps
    int X_AllocColor
    int X_AllocNamedColor
    int X_AllocColorCells
    int X_AllocColorPlanes
    int X_FreeColors
    int X_StoreColors
    int X_StoreNamedColor
    int X_QueryColors
    int X_LookupColor
    int X_CreateCursor
    int X_CreateGlyphCursor
    int X_FreeCursor
    int X_RecolorCursor
    int X_QueryBestSize
    int X_QueryExtension
    int X_ListExtensions
    int X_ChangeKeyboardMapping
    int X_GetKeyboardMapping
    int X_ChangeKeyboardControl
    int X_GetKeyboardControl
    int X_Bell
    int X_ChangePointerControl
    int X_GetPointerControl
    int X_SetScreenSaver
    int X_GetScreenSaver
    int X_ChangeHosts
    int X_ListHosts
    int X_SetAccessControl
    int X_SetCloseDownMode
    int X_KillClient
    int X_RotateProperties
    int X_ForceScreenSaver
    int X_SetPointerMapping
    int X_GetPointerMapping
    int X_SetModifierMapping
    int X_GetModifierMapping
    int X_NoOperation

    ctypedef struct xReq:
        CARD8 reqType
        CARD8 data          # meaning depends on request type
        CARD16 length       # length in 4 bytes quantities

    ctypedef struct xGrabPointerReq:
        CARD8 reqType
        BOOL ownerEvents
        CARD16 length
        Window grabWindow
        CARD16 eventMask
        BYTE pointerMode, keyboardMode
        Window confineTo
        Cursor cursor
        Time time

    ctypedef struct xGrabButtonReq:
        CARD8 reqType
        BOOL ownerEvents
        CARD16 length
        Window grabWindow
        CARD16 eventMask
        BYTE pointerMode, keyboardMode
        Window confineTo
        Cursor cursor
        CARD8 button
        BYTE pad
        CARD16 modifiers

    ctypedef struct xUngrabButtonReq:
        CARD8 reqType
        CARD8 button
        CARD16 length
        Window grabWindow
        CARD16 modifiers
        CARD16 pad

    ctypedef struct xGrabKeyboardReq:
        CARD8 reqType
        BOOL ownerEvents
        CARD16 length
        Window grabWindow
        Time time
        BYTE pointerMode, keyboardMode
        CARD16 pad

    ctypedef struct xGrabKeyReq:
        CARD8 reqType
        BOOL ownerEvents
        CARD16 length
        Window grabWindow
        CARD16 modifiers
        CARD8 key
        BYTE pointerMode, keyboardMode
        BYTE pad1, pad2, pad3

    ctypedef struct xChangeActivePointerGrabReq:
        CARD8 reqType
        BYTE pad
        CARD16 length
        Cursor cursor
        Time time
        CARD16 eventMask
        CARD16 pad2

    ctypedef struct xUngrabKeyReq:
        CARD8 reqType
        CARD8 key
        CARD16 length
        CARD32 grabWindow
        CARD16 modifiers
        CARD16 pad


cdef extern from "X11/Xlib.h":
    ctypedef char *XPointer


cdef extern from "X11/extensions/recordconst.h":
    int XRecordAllClients
    int XRecordFromServer
    int XRecordFromClient
    int XRecordClientStarted
    int XRecordClientDied
    int XRecordStartOfData
    int XRecordEndOfData


cdef extern from "X11/extensions/record.h":

    ctypedef struct XRecordRange8:
        unsigned char       first
        unsigned char       last

    ctypedef struct XRecordRange16:
        unsigned short      first
        unsigned short      last

    ctypedef struct XRecordExtRange:
        XRecordRange8       ext_major
        XRecordRange16      ext_minor

    ctypedef struct XRecordRange:
        XRecordRange8     core_requests     # core X requests
        XRecordRange8     core_replies      # core X repliess
        XRecordExtRange   ext_requests      # extension requests
        XRecordExtRange   ext_replies       # extension replies
        XRecordRange8     delivered_events  # delivered core and ext events
        XRecordRange8     device_events     # all core and ext device events
        XRecordRange8     errors            # core X and ext errors
        BOOL              client_started    # connection setup reply
        BOOL              client_died       # notice of client disconnect

    ctypedef struct XRecordClientInfo:
        XRecordClientSpec   client
        unsigned long       nranges
        XRecordRange        **ranges

    ctypedef struct XRecordState:
        BOOL                enabled
        int                 datum_flags
        unsigned long       nclients
        XRecordClientInfo   **client_info

    ctypedef struct XRecordInterceptData:
        XID                 id_base
        Time                server_time
        unsigned long       client_seq
        int                 category
        BOOL                client_swapped
        unsigned char       *data
        unsigned long       data_len            # in 4-byte units

    Status XRecordQueryVersion(Display * display, int *cmajor_return, int *cminor_return)

    XRecordContext XRecordCreateContext(Display *dpy,
                                        int datum_flags,
                                        XRecordClientSpec *clients, int nclients,
                                        XRecordRange **ranges, int nranges)

    XRecordRange *XRecordAllocRange()

    Status XRecordRegisterClients(Display *dpy, XRecordContext context,
                                  int datum_flags,
                                  XRecordClientSpec *clients, int nclients,
                                  XRecordRange **ranges, int nranges)

    Status XRecordUnregisterClients(Display *dpy, XRecordContext context,
                                    XRecordClientSpec *clients, int nclients)

    Status XRecordGetContext(Display *dpy, XRecordContext context, XRecordState **state_return)

    void XRecordFreeState(XRecordState *state)

    ctypedef void *XRecordInterceptProc(XPointer closure, XRecordInterceptData recorded_data) noexcept

    Status XRecordEnableContext(Display *dpy, XRecordContext context,
                                void *callback, XPointer closure)

    Status XRecordEnableContextAsync(Display *dpy, XRecordContext context,
                                     void *callback, XPointer closure)

    void XRecordProcessReplies(Display *dpy)

    void XRecordFreeData(XRecordInterceptData *data)

    Status XRecordDisableContext(Display *dpy, XRecordContext context)

    Status XRecordFreeContext(Display *dpy, XRecordContext context)


CATEGORIES: dict[int, str] = {
    XRecordFromServer: "from-server",
    XRecordFromClient: "from-client",
    XRecordClientStarted: "cient-started",
    XRecordClientDied: "client-died",
    XRecordStartOfData: "start-of-data",
    XRecordEndOfData: "end-of-data",
}

EVENT_TYPES: dict[int, str] = {
    X_CreateWindow: "CreateWindow",
    X_ChangeWindowAttributes: "ChangeWindowAttributes",
    X_GetWindowAttributes: "GetWindowAttributes",
    X_DestroyWindow: "DestroyWindow",
    X_DestroySubwindows: "DestroySubwindows",
    X_ChangeSaveSet: "ChangeSaveSet",
    X_ReparentWindow: "ReparentWindow",
    X_MapWindow: "MapWindow",
    X_MapSubwindows: "MapSubwindows",
    X_UnmapWindow: "UnmapWindow",
    X_UnmapSubwindows: "UnmapSubwindows",
    X_ConfigureWindow: "ConfigureWindow",
    X_CirculateWindow: "CirculateWindow",
    X_GetGeometry: "GetGeometry",
    X_QueryTree: "QueryTree",
    X_InternAtom: "InternAtom",
    X_GetAtomName: "GetAtomName",
    X_ChangeProperty: "ChangeProperty",
    X_DeleteProperty: "DeleteProperty",
    X_GetProperty: "GetProperty",
    X_ListProperties: "ListProperties",
    X_SetSelectionOwner: "SetSelectionOwner",
    X_GetSelectionOwner: "GetSelectionOwner",
    X_ConvertSelection: "ConvertSelection",
    X_SendEvent: "SendEvent",
    X_GrabPointer: "GrabPointer",
    X_UngrabPointer: "UngrabPointer",
    X_GrabButton: "GrabButton",
    X_UngrabButton: "UngrabButton",
    X_ChangeActivePointerGrab: "ChangeActivePointerGrab",
    X_GrabKeyboard: "GrabKeyboard",
    X_UngrabKeyboard: "UngrabKeyboard",
    X_GrabKey: "GrabKey",
    X_UngrabKey: "UngrabKey",
    X_AllowEvents: "AllowEvents",
    X_GrabServer: "GrabServer",
    X_UngrabServer: "UngrabServer",
    X_QueryPointer: "QueryPointer",
    X_GetMotionEvents: "GetMotionEvents",
    X_TranslateCoords: "TranslateCoords",
    X_WarpPointer: "WarpPointer",
    X_SetInputFocus: "SetInputFocus",
    X_GetInputFocus: "GetInputFocus",
    X_QueryKeymap: "QueryKeymap",
    X_OpenFont: "OpenFont",
    X_CloseFont: "CloseFont",
    X_QueryFont: "QueryFont",
    X_QueryTextExtents: "QueryTextExtents",
    X_ListFonts: "ListFonts",
    X_ListFontsWithInfo: "ListFontsWithInfo",
    X_SetFontPath: "SetFontPath",
    X_GetFontPath: "GetFontPath",
    X_CreatePixmap: "CreatePixmap",
    X_FreePixmap: "FreePixmap",
    X_CreateGC: "CreateGC",
    X_ChangeGC: "ChangeGC",
    X_CopyGC: "CopyGC",
    X_SetDashes: "SetDashes",
    X_SetClipRectangles: "SetClipRectangles",
    X_FreeGC: "FreeGC",
    X_ClearArea: "ClearArea",
    X_CopyArea: "CopyArea",
    X_CopyPlane: "CopyPlane",
    X_PolyPoint: "PolyPoint",
    X_PolyLine: "PolyLine",
    X_PolySegment: "PolySegment",
    X_PolyRectangle: "PolyRectangle",
    X_PolyArc: "PolyArc",
    X_FillPoly: "FillPoly",
    X_PolyFillRectangle: "PolyFillRectangle",
    X_PolyFillArc: "PolyFillArc",
    X_PutImage: "PutImage",
    X_GetImage: "GetImage",
    X_PolyText8: "PolyText8",
    X_PolyText16: "PolyText16",
    X_ImageText8: "ImageText8",
    X_ImageText16: "ImageText16",
    X_CreateColormap: "CreateColormap",
    X_FreeColormap: "FreeColormap",
    X_CopyColormapAndFree: "CopyColormapAndFree",
    X_InstallColormap: "InstallColormap",
    X_UninstallColormap: "UninstallColormap",
    X_ListInstalledColormaps: "ListInstalledColormaps",
    X_AllocColor: "AllocColor",
    X_AllocNamedColor: "AllocNamedColor",
    X_AllocColorCells: "AllocColorCells",
    X_AllocColorPlanes: "AllocColorPlanes",
    X_FreeColors: "FreeColors",
    X_StoreColors: "StoreColors",
    X_StoreNamedColor: "StoreNamedColor",
    X_QueryColors: "QueryColors",
    X_LookupColor: "LookupColor",
    X_CreateCursor: "CreateCursor",
    X_CreateGlyphCursor: "CreateGlyphCursor",
    X_FreeCursor: "FreeCursor",
    X_RecolorCursor: "RecolorCursor",
    X_QueryBestSize: "QueryBestSize",
    X_QueryExtension: "QueryExtension",
    X_ListExtensions: "ListExtensions",
    X_ChangeKeyboardMapping: "ChangeKeyboardMapping",
    X_GetKeyboardMapping: "GetKeyboardMapping",
    X_ChangeKeyboardControl: "ChangeKeyboardControl",
    X_GetKeyboardControl: "GetKeyboardControl",
    X_Bell: "Bell",
    X_ChangePointerControl: "ChangePointerControl",
    X_GetPointerControl: "GetPointerControl",
    X_SetScreenSaver: "SetScreenSaver",
    X_GetScreenSaver: "GetScreenSaver",
    X_ChangeHosts: "ChangeHosts",
    X_ListHosts: "ListHosts",
    X_SetAccessControl: "SetAccessControl",
    X_SetCloseDownMode: "SetCloseDownMode",
    X_KillClient: "KillClient",
    X_RotateProperties: "RotateProperties",
    X_ForceScreenSaver: "ForceScreenSaver",
    X_SetPointerMapping: "SetPointerMapping",
    X_GetPointerMapping: "GetPointerMapping",
    X_SetModifierMapping: "SetModifierMapping",
    X_GetModifierMapping: "GetModifierMapping",
    X_NoOperation: "NoOperation",
}


cdef dict parse_GrabPointer(xGrabPointerReq *rec):
    return {
        "window": rec.grabWindow,
        "pointer-mode": rec.pointerMode,
        "keyboard-mode": rec.keyboardMode,
        "confine-to": rec.confineTo,
        "time": rec.time,
    }

cdef dict parse_GrabButton(xGrabButtonReq *rec):
    return {
        "window": rec.grabWindow,
        "owner-events": rec.ownerEvents,
        "event-mask": rec.eventMask,
        "pointer-mode": rec.pointerMode,
        "keyboard-mode": rec.keyboardMode,
        "confine-to": rec.confineTo,
        "cursor": rec.cursor,
        "button": rec.button,
        "modifiers": rec.modifiers,
    }

cdef dict parse_UngrabButton(xUngrabButtonReq *rec):
    return {
        "window": rec.grabWindow,
        "button": rec.button,
        "modifiers": rec.modifiers,
    }

cdef dict parse_ChangeActivePointerGrab(xChangeActivePointerGrabReq *rec):
    return {
        "cursor": rec.cursor,
        "event-mask": rec.eventMask,
        "time": rec.time,
    }

cdef dict parse_GrabKeyboard(xGrabKeyboardReq *rec):
    return {
        "window": rec.grabWindow,
        "owner-events": rec.ownerEvents,
        "time": rec.time,
        "pointer-mode": rec.pointerMode,
        "keyboard-mode": rec.keyboardMode,
    }

cdef dict parse_GrabKey(xGrabKeyReq *rec):
    return {
        "window": rec.grabWindow,
        "owner-events": rec.ownerEvents,
        "modifiers": rec.modifiers,
        "pointer-mode": rec.pointerMode,
        "keyboard-mode": rec.keyboardMode,
    }


cdef dict parse_UngrabKey(xUngrabKeyReq *rec):
    return {
        "window": rec.grabWindow,
        "key": rec.key,
        "modifiers": rec.modifiers,
    }


cdef void event_callback(XPointer closure, XRecordInterceptData *rec) noexcept:
    cdef xReq * req = < xReq * > rec.data
    if rec.category == XRecordStartOfData:
        log.info("start of X11 record data")
        return
    if rec.category == XRecordClientStarted:
        log.info("X11 client started")
        return
    if rec.category == XRecordClientDied:
        log.info("X11 client died")
        return
    log("XRecordInterceptData id_base=%s, server_time=%s, client_seq=%s",
        rec.id_base, rec.server_time, rec.client_seq)

    category = CATEGORIES.get(rec.category, "unknown")
    try:
        if rec.category not in (XRecordFromServer, XRecordFromClient):
            log.warn(f"unexpected event category {category}")
            return

        event_type = EVENT_TYPES.get(req.reqType, f"unknown: {req.reqType}")
        event = {}
        if req.reqType == X_GrabPointer:
            event = parse_GrabPointer(< xGrabPointerReq * > rec.data)
        elif req.reqType == X_UngrabPointer:
            # no data associated with it
            pass
        elif req.reqType == X_GrabButton:
            event = parse_GrabButton(< xGrabButtonReq * > rec.data)
        elif req.reqType == X_UngrabButton:
            event = parse_UngrabButton(< xUngrabButtonReq * > rec.data)
        elif req.reqType == X_ChangeActivePointerGrab:
            event = parse_ChangeActivePointerGrab(< xChangeActivePointerGrabReq * > rec.data)
        elif req.reqType == X_GrabKeyboard:
            event = parse_GrabKeyboard(< xGrabKeyboardReq *> rec.data)
        elif req.reqType == X_UngrabKeyboard:
            # no data?
            pass
        elif req.reqType == X_GrabKey:
            event = parse_GrabKey(< xGrabKeyReq * > rec.data)
        elif req.reqType == X_UngrabKey:
            event = parse_UngrabKey(<xUngrabKeyReq*> rec.data)
        log.info(f"{category} event type={event_type} {event}")
    except KeyboardInterrupt:
        log.info(f"KeyboardInterrupt")
        RecordBindings().stop()
    except Exception:
        log.error("Error in X11 record event callback", exc_info=True)
    finally:
        XRecordFreeData(rec)


cdef class RecordBindingsInstance(X11CoreBindingsInstance):

    cdef object version
    cdef int stop_flag
    cdef int all
    cdef XRecordContext rc

    def __init__(self):
        self.stop_flag = 0
        self.all = False
        self.version = self.query_version()
        # open new X11 connection:
        cdef Display *display = NULL
        try:
            display = XOpenDisplay(self.display_name)
        except Exception as e:
            log(f"XOpenDisplay{self.display_name}", exc_info=True)
            log.error("Error: failed to open the display again")
            log.error(f" {e}")
        if display != NULL:
            self.display = display
        else:
            raise RuntimeError("unable to use the X11 record extension")

    def __repr__(self):
        return f"RecordBindings({self.display_name})"

    def get_version(self):
        return self.version

    def query_version(self):
        cdef int event_base = 0, ignored = 0, cmajor = 0, cminor = 0
        cdef int r = XRecordQueryVersion(self.display, &cmajor, &cminor)
        log(f"found XRecord extension version {cmajor}.{cminor}")
        return cmajor, cminor

    def stop(self):
        self.stop_flag = 1
        self.cleanup()

    def get_info(self) -> dict:
        return {
            "version": self.get_version(),
        }

    def record(self):
        cdef XRecordClientSpec rcs
        cdef XRecordRange * rr = XRecordAllocRange()
        if not rr:
            raise RuntimeError("Could not alloc record range object")
        rr.client_started = True
        rr.client_died = True
        if self.all:
            first = X_CreateWindow
            last = X_NoOperation
        else:
            first = X_GrabPointer
            last = X_UngrabKey
        rr.core_requests.first = first
        rr.core_requests.last = last
        #rr.delivered_events.first = first
        #rr.delivered_events.last = last
        rcs = XRecordAllClients

        cdef int record_fd = XConnectionNumber(self.display)

        self.rc = XRecordCreateContext(self.display, 0, &rcs, 1, &rr, 1)
        if not self.rc:
            raise RuntimeError("Could not create a record context")

        if not XRecordEnableContextAsync(self.display, self.rc, &event_callback, NULL):
            raise RuntimeError("Cound not enable the record context")

        try:
            while not self.stop_flag:
                pending = XPending(self.display)
                if not pending:
                    r_fd, _, _ = select([record_fd], [], [])
                    log(f"select: {r_fd}")
                    if not r_fd:
                        log.info("exiting on empty select")
                        break
                else:
                    log(f"XRecordProcessReplies pending={pending}")
                XRecordProcessReplies(self.display)
        except KeyboardInterrupt:
            self.stop_flag = True
            log("KeyboardInterrupt", exc_info=True)
            log.info("exiting on KeyboardInterrupt")
        self.cleanup()
        XFree(rr)

    def cleanup(self):
        XRecordDisableContext(self.display, self.rc)
        XRecordFreeContext(self.display, self.rc)
        self.rc = 0
        XFlush(self.display)
        XSync(self.display, False)
        # XCloseDisplay(display)


cdef RecordBindingsInstance singleton = None


def RecordBindings() -> RecordBindingsInstance:
    global singleton
    if singleton is None:
        singleton = RecordBindingsInstance()
    return singleton
