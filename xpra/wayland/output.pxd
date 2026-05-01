# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.wayland.wlroots cimport wlr_output


cdef class Output:
    pass

cdef object get_output_info(wlr_output *output)
