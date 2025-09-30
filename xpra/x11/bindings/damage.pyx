# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.x11.bindings.xlib cimport Display, Drawable, XID, XRectangle, Bool, Status, XEvent
from xpra.x11.bindings.display_source cimport get_display
from xpra.x11.bindings.events cimport add_parser, add_event_type
from xpra.x11.bindings.core cimport X11CoreBindingsInstance, import_check

from xpra.log import Logger

import_check("damage")

log = Logger("x11", "bindings", "damage")


DEF XNone = 0


cdef extern from "X11/extensions/Xdamage.h":
    ctypedef XID Damage
    ctypedef XID XserverRegion
    unsigned int XDamageNotify
    unsigned int XDamageReportDeltaRectangles
    #unsigned int XDamageReportRawRectangles

    ctypedef struct XDamageNotifyEvent:
        Damage damage
        int level
        Bool more
        XRectangle area

    Bool XDamageQueryExtension(Display *, int * event_base, int * error_base)
    Status XDamageQueryVersion(Display *, int * major, int * minor)
    Damage XDamageCreate(Display *, Drawable, int level)
    void XDamageDestroy(Display *, Damage)
    void XDamageSubtract(Display *, Damage, XserverRegion repair, XserverRegion parts)


def init_damage_events() -> bool:
    cdef Display *display = get_display()
    cdef int event_base = 0, error_base = 0
    if not XDamageQueryExtension(display, &event_base, &error_base):
        log.warn("Warning: XDamage extension is not available")
        return False
    if event_base <= 0:
        log.warn("Warning: XDamage extension returned invalid event base: %d", event_base)
        return False
    cdef int DamageNotify = event_base + XDamageNotify
    log("DamageNotify=%d", DamageNotify)
    add_event_type(DamageNotify, "DamageNotify", "x11-damage-event", "")
    add_parser(DamageNotify, parse_DamageNotify)
    return True


cdef dict parse_DamageNotify(Display *d, XEvent *e):
    cdef XDamageNotifyEvent * damage_e = <XDamageNotifyEvent*>e
    return {
        "window": e.xany.window,
        "damage": damage_e.damage,
        "level": damage_e.level,
        "more": damage_e.more,
        "x": damage_e.area.x,
        "y": damage_e.area.y,
        "width": damage_e.area.width,
        "height": damage_e.area.height,
    }


cdef class XDamageBindingsInstance(X11CoreBindingsInstance):

    def ensure_XDamage_support(self) -> None:
        cdef int event_base = 0, ignored = 0
        if not XDamageQueryExtension(self.display, &event_base, &ignored):
            raise ValueError("X11 Damage extension %s not available")
        log("X11 Damage extension event_base=%i", event_base)
        cdef int major = 1, minor = 0
        if XDamageQueryVersion(self.display, &major, &minor):
            # See X.org bug #14511:
            log("found Damage extension version %i.%i", major, minor)
            if (major, minor) < (1, 0):
                raise ValueError("Damage extension is too old")

    def XDamageCreate(self, Drawable xwindow) -> None:
        self.context_check("XDamageCreate")
        return XDamageCreate(self.display, xwindow, XDamageReportDeltaRectangles)

    def XDamageDestroy(self, Damage handle) -> None:
        self.context_check("XDamageDestroy")
        XDamageDestroy(self.display, handle)

    def XDamageSubtract(self, Damage handle) -> None:
        self.context_check("XDamageSubtract")
        # def xdamage_acknowledge(display_source, handle, x, y, width, height):
        # cdef XRectangle rect
        # rect.x = x
        # rect.y = y
        # rect.width = width
        # rect.height = height
        # repair = XFixesCreateRegion(display, &rect, 1)
        # XDamageSubtract(display, handle, repair, XNone)
        # XFixesDestroyRegion(display, repair)

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


cdef XDamageBindingsInstance singleton = None


def XDamageBindings() -> XDamageBindingsInstance:
    global singleton
    if singleton is None:
        singleton = XDamageBindingsInstance()
    return singleton
