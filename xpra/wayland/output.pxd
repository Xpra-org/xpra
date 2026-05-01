# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.wayland.wlroots cimport wl_signal, wl_listener, wl_list, wlr_output, wlr_scene_output
from xpra.wayland.events cimport xpra_listener


cdef class Output:
    cdef wlr_output *wlr_output
    cdef wlr_scene_output *scene_output
    cdef readonly str name
    cdef xpra_listener listeners[2]  # must equal N_LISTENERS

    cdef void initialize(self)
    cdef void output_frame(self) noexcept nogil
    cdef void destroy(self) noexcept nogil

    cdef inline void add_listener(self, int slot, wl_signal *signal) noexcept
    cdef inline int slot_of(self, wl_listener *l) noexcept nogil
    cdef inline void _detach_slot(self, int slot) noexcept nogil
    cdef inline void _detach_all(self) noexcept nogil
    cdef void add_main_listeners(self)
    cdef void dispatch(self, wl_listener *listener, void *data) noexcept
