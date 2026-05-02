# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.wayland.wlroots cimport wl_listener, wlr_subsurface
from xpra.wayland.wayland_surface cimport WaylandSurface


cdef class Subsurface(WaylandSurface):
    cdef wlr_subsurface *wlr_subsurface
    cdef WaylandSurface parent              # the wrapper that owns this subsurface

    cdef void attach(self, WaylandSurface parent, wlr_subsurface *subsurface)
    cdef void dispatch(self, wl_listener *listener, void *data) noexcept
    cdef void commit(self) noexcept
    cdef void destroy(self) noexcept
