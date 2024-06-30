# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.x11.bindings.xlib cimport Display, XEvent

cdef object parse_xevent(Display *d, XEvent *e)
cdef void init_x11_events(Display *display)
