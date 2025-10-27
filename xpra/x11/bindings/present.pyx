# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from libc.stdint cimport uint8_t, uint16_t, uint32_t, uint64_t

from xpra.x11.bindings.xlib cimport Display, Window, Pixmap, Bool, Atom, XID, XEvent, CARD8, CARD16, CARD32
from xpra.x11.bindings.display_source cimport get_display
from xpra.x11.bindings.events cimport add_parser, add_event_type
from xpra.x11.bindings.core cimport X11CoreBindingsInstance, import_check

from xpra.log import Logger

import_check("present")

log = Logger("x11", "bindings", "present")


DEF XNone = 0

cdef extern from "X11/Xmd.h":
    pass


cdef extern from "X11/extensions/Xpresent.h":
    ctypedef XID XSyncFence
    ctypedef struct Region:
        pass

    cdef enum:
        PRESENT_MAJOR  # 1
        PRESENT_MINOR  # 4 (as of latest version)

    cdef enum:
        PresentConfigureNotify
        PresentCompleteNotify
        # PresentRedirectNotify
        PresentIdleNotify

    cdef enum:
        PresentConfigureNotifyMask
        PresentCompleteNotifyMask
        PresentIdleNotifyMask
        # PresentRedirectNotifyMask
        PresentAllEvents

    cdef enum:
        PresentOptionNone
        PresentOptionAsync
        PresentOptionCopy
        PresentOptionUST
        PresentOptionSuboptimal

    cdef enum:
        PresentCapabilityNone
        PresentCapabilityAsync
        PresentCapabilityFence
        PresentCapabilityUST

    cdef enum:
        PresentCompleteKindPixmap
        PresentCompleteKindNotifyMSC

    cdef enum:
        PresentCompleteModeCopy
        PresentCompleteModeFlip
        PresentCompleteModeSkip
        PresentCompleteModeSuboptimalCopy

    ctypedef uint32_t PresentEventID
    ctypedef uint64_t PresentEventSerial

    # Notify structure for PresentNotifyMSC
    ctypedef struct XPresentNotify:
        Window window
        uint32_t serial

    ctypedef struct XPresentEvent:
        int type
        unsigned long serial
        Bool send_event
        Display *display
        int extension
        int evtype

    ctypedef struct XPresentConfigureNotifyEvent:
        int type
        unsigned long serial
        Bool send_event
        Display *display
        int extension
        int evtype
        Window window
        int x
        int y
        unsigned int width
        unsigned int height
        int off_x
        int off_y
        unsigned int pixmap_width
        unsigned int pixmap_height
        unsigned long pixmap_flags

    ctypedef struct XPresentCompleteNotifyEvent:
        int type
        unsigned long serial
        Bool send_event
        Display *display
        int extension
        int evtype
        uint32_t eid
        Window window
        uint32_t serial_number
        uint64_t ust           # UST timestamp
        uint64_t msc           # Media Stream Counter
        uint8_t kind           # PresentCompleteKind
        uint8_t mode           # PresentCompleteMode

    ctypedef struct XPresentIdleNotifyEvent:
        int type
        unsigned long serial
        Bool send_event
        Display *display
        int extension
        int evtype
        Window window
        uint32_t eid
        uint32_t serial_number
        Pixmap pixmap
        XSyncFence idle_fence

    ctypedef struct XPresentRedirectNotifyEvent:
        int type
        unsigned long serial
        Bool send_event
        Display *display
        int extension
        int evtype
        Window window
        uint32_t event_serial
        Pixmap pixmap
        uint32_t valid_region
        uint32_t update_region
        int x_off
        int y_off
        uint32_t target_crtc
        uint32_t wait_fence
        uint32_t idle_fence
        uint32_t options
        uint64_t target_msc
        uint64_t divisor
        uint64_t remainder
        # Notifies follow

    Bool XPresentQueryExtension(Display *display, int *major_opcode, int *event_base, int *error_base)
    Bool XPresentQueryVersion(Display *display, int *major_version, int *minor_version)
    int XPresentVersion()
    void XPresentPixmap(Display *display, Window window, Pixmap pixmap,
                        uint32_t serial, Region valid, Region update,
                        int x_off, int y_off, void *target_crtc,
                        void *wait_fence,   # XSyncFence
                        void *idle_fence,   # XSyncFence
                        uint32_t options,
                        uint64_t target_msc,
                        uint64_t divisor,
                        uint64_t remainder,
                        XPresentNotify *notifies,
                        int nnotifies)

    void XPresentNotifyMSC(Display *display, Window window,
                           uint32_t serial, uint64_t target_msc, uint64_t divisor, uint64_t remainder)

    XID XPresentSelectInput(Display *display, Window window, unsigned int event_mask)
    void XPresentFreeInput(Display *dpy, Window window, XID event_id)

    # Query capabilities
    uint32_t XPresentQueryCapabilities(Display *display, XID target)


def init_present_events() -> bool:
    cdef Display *display = get_display()
    cdef int major_opcode, event_base = 0, error_base = 0
    if not XPresentQueryExtension(display, &major_opcode, &event_base, &error_base):
        log.warn("Warning: XPresent extension is not available")
        return False
    log("init_present_events() major_opcode=%i, event_base=%i, error_base=%i", major_opcode, event_base, error_base)
    if major_opcode <= 0:
        log.warn("Warning: XPresent extension returned invalid major opcode: %d", major_opcode)
        return False

    cdef int major, minor
    if not XPresentQueryVersion(display, &major, &minor):
        log.warn("Warning: unable to query XPresent extension version")
        return False
    log("XPresent version %i.%i", major, minor)

    cdef int ConfigureNotify = major_opcode + PresentConfigureNotify
    cdef int CompleteNotify = major_opcode + PresentCompleteNotify
    cdef int IdleNotify = major_opcode + PresentIdleNotify
    # cdef int RedirectNotify = major_opcode + PresentRedirectNotify
    log("PresentConfigureNotify=%i, PresentCompleteNotify=%i, PresentIdleNotify=%i",
        ConfigureNotify, CompleteNotify, IdleNotify)
    add_event_type(ConfigureNotify, "PresentConfigureNotify", "x11-present-configure-event", "")
    add_parser(ConfigureNotify, parse_PresentConfigureNotify)
    add_event_type(CompleteNotify, "PresentCompleteNotify", "x11-present-complete-event", "")
    add_parser(CompleteNotify, parse_PresentCompleteNotify)
    add_event_type(IdleNotify, "PresentIdleNotify", "x11-present-idle-event", "")
    add_parser(IdleNotify, parse_PresentIdleNotify)
    return True


cdef dict parse_PresentConfigureNotify(Display *d, XEvent *e):
    cdef XPresentConfigureNotifyEvent * conf_e = <XPresentConfigureNotifyEvent*> e
    return {
        "extension": conf_e.extension,
        "evtype": conf_e.evtype,
        "window": conf_e.window,
        "x": conf_e.x,
        "y": conf_e.y,
        "width": conf_e.width,
        "height": conf_e.height,
        "off_x": conf_e.off_x,
        "off_y": conf_e.off_y,
        "pixmap_width": conf_e.pixmap_width,
        "pixmap_height": conf_e.pixmap_height,
        "pixmap_flags": conf_e.pixmap_flags,
    }

cdef dict parse_PresentCompleteNotify(Display *d, XEvent *e):
    cdef XPresentCompleteNotifyEvent * complete_e = <XPresentCompleteNotifyEvent*> e
    return {
        "extension": complete_e.extension,
        "evtype": complete_e.evtype,
        "window": complete_e.window,
        "eid": complete_e.eid,
        "serial_number": complete_e.serial_number,
        "ust": complete_e.ust,
        "msc": complete_e.msc,
        "kind": complete_e.kind,
        "mode": complete_e.mode,
    }

cdef dict parse_PresentIdleNotify(Display *d, XEvent *e):
    cdef XPresentIdleNotifyEvent *idle_e = <XPresentIdleNotifyEvent*> e
    return {
        "extension": idle_e.extension,
        "evtype": idle_e.evtype,
        "window": idle_e.window,
        "eid": idle_e.eid,
        "serial_number": idle_e.serial_number,
        "pixmap": idle_e.pixmap,
        "xsync-fence": idle_e.idle_fence,
    }


cdef class XPresentBindingsInstance(X11CoreBindingsInstance):

    def SelectInput(self, Window window, unsigned int event_mask = PresentAllEvents) -> None:
        return XPresentSelectInput(self.display, window, event_mask)

    def FreeInput(self, Window window, XID event_id) -> None:
        XPresentFreeInput(self.display, window, event_id)

    def QueryCapabilities(self, XID target) -> int:
        return XPresentQueryCapabilities(self.display, target)


cdef XPresentBindingsInstance singleton = None


def XPresentBindings() -> XPresentBindingsInstance:
    global singleton
    if singleton is None:
        singleton = XPresentBindingsInstance()
    return singleton
