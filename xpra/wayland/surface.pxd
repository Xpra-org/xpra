# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from libc.stdint cimport uint32_t
from xpra.wayland.wlroots cimport (
    wlr_xdg_surface,
    wlr_scene_tree,
    wl_signal,
    wl_listener,
    wlr_subsurface,
)
from xpra.wayland.events cimport xpra_listener


cdef class Surface:
    cdef wlr_xdg_surface *wlr_xdg_surface
    cdef wlr_scene_tree *scene_tree
    cdef xpra_listener listeners[12]  # must equal N_LISTENERS
    cdef int width
    cdef int height
    cdef str title
    cdef str app_id
    cdef readonly unsigned long wid
    cdef dict _callbacks  # {event_name: [callable, ...]}

    cdef inline void add_listener(self, int slot, wl_signal *signal) noexcept
    cdef inline int slot_of(self, wl_listener *l) noexcept nogil
    cdef inline void _detach_slot(self, int slot) noexcept nogil
    cdef inline void _detach_all(self) noexcept nogil
    cdef add_main_listeners(self)
    cdef void register_toplevel_handlers(self) noexcept
    cdef void map(self) noexcept
    cdef void unmap(self) noexcept
    cdef void destroy(self) noexcept
    cdef void request_move(self, uint32_t serial) noexcept
    cdef void request_resize(self, uint32_t edges, uint32_t serial) noexcept
    cdef void request_maximize(self) noexcept
    cdef void request_fullscreen(self) noexcept
    cdef void request_minimize(self) noexcept
    cdef void set_title(self) noexcept
    cdef void set_app_id(self) noexcept
    cdef void commit(self) noexcept
    cdef void capture_surface_pixels(self) noexcept
    cdef void new_subsurface(self, wlr_subsurface *subsurface) noexcept
    cdef void unregister_toplevel_handlers(self) noexcept nogil