# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.x11.bindings.xlib cimport Display, Window, Visual, XID, XRectangle, Bool, XEvent
from xpra.x11.bindings.display_source cimport get_display
from xpra.x11.bindings.events cimport add_parser, new_x11_event, add_event_type

from xpra.log import Logger

log = Logger("x11", "bindings", "damage")


cdef extern from "X11/extensions/Xdamage.h":
    ctypedef XID Damage
    unsigned int XDamageNotify
    ctypedef struct XDamageNotifyEvent:
        Damage damage
        int level
        Bool more
        XRectangle area
    Bool XDamageQueryExtension(Display *, int * event_base, int * error_base)


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


cdef object parse_DamageNotify(Display *d, XEvent *e):
    cdef XDamageNotifyEvent * damage_e = <XDamageNotifyEvent*>e
    pyev = new_x11_event(e)
    pyev.window = e.xany.window
    pyev.damage = damage_e.damage
    pyev.x = damage_e.area.x
    pyev.y = damage_e.area.y
    pyev.width = damage_e.area.width
    pyev.height = damage_e.area.height
    return pyev
