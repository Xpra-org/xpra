# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.wayland.wlroots cimport wl_signal, wl_listener, wl_list, wlr_output, wlr_output_layout, wlr_scene_output
from xpra.wayland.events cimport ListenerObject


cdef class Output(ListenerObject):
    cdef wlr_output *wlr_output
    cdef wlr_output_layout *output_layout
    cdef wlr_scene_output *scene_output
    cdef readonly str name

    cdef void initialize(self)
    cdef void output_frame(self) noexcept nogil
    cdef void destroy(self) noexcept nogil

    cdef void add_main_listeners(self)
    cdef void dispatch(self, wl_listener *listener, void *data) noexcept
