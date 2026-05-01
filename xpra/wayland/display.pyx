# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# cython: language_level=3

from libc.stdint cimport uintptr_t


# Import definitions from .pxd file
from xpra.wayland.wlroots cimport wl_display, wl_display_flush_clients


cdef class Display:

    def __cinit__(self):
        self.display = NULL

    def __repr__(self):
        return "Display(%#x)" % (<uintptr_t> self.display)

    def flush_clients(self) -> None:
        if display := self.display:
            wl_display_flush_clients(display)


