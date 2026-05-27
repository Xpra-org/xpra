# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.wayland.wlroots cimport wl_listener, wlr_seat, wlr_surface
from xpra.wayland.wayland_surface cimport WaylandSurface
from xpra.wayland.events cimport ListenerObject


cdef class CursorSurface(WaylandSurface):
    cdef int hotspot_x
    cdef int hotspot_y

    cdef void attach(self, wlr_surface *surface, int hotspot_x, int hotspot_y)
    cdef void update_hotspot(self, int hotspot_x, int hotspot_y)
    cdef void refresh(self)
    cdef void dispatch(self, wl_listener *listener, void *data) noexcept
    cdef void commit(self) noexcept
    cdef void destroy(self) noexcept


cdef class SeatCursorTracker(ListenerObject):
    cdef wlr_seat *seat
    cdef object callback
    cdef CursorSurface cursor_surface

    cdef void dispatch(self, wl_listener *listener, void *data) noexcept
    cdef void request_set_cursor(self, void *data) noexcept
    cdef void emit_cursor(self, object image, int hotspot_x, int hotspot_y)
