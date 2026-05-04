# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from libc.stdint cimport uint32_t
from xpra.wayland.wlroots cimport wl_listener, wlr_xdg_popup, wlr_xdg_surface
from xpra.wayland.wayland_surface cimport WaylandSurface


cdef class Popup(WaylandSurface):
    cdef wlr_xdg_popup *wlr_xdg_popup
    cdef wlr_xdg_surface *wlr_xdg_surface
    cdef WaylandSurface parent
    cdef int x
    cdef int y

    cdef void attach(self, WaylandSurface parent, wlr_xdg_popup *popup)
    cdef void dispatch(self, wl_listener *listener, void *data) noexcept
    cdef void map(self) noexcept
    cdef void unmap(self) noexcept
    cdef void commit(self) noexcept
    cdef void reposition(self) noexcept
    cdef void destroy(self) noexcept
    cdef tuple position(self)
