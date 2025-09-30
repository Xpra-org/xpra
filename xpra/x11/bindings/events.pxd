# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.x11.bindings.xlib cimport Display, XEvent, Atom

cdef object parse_xevent(Display *d, XEvent *e)
cdef void init_x11_events()
cdef void add_event_type(int event, str name, str event_name, str child_event_name) noexcept

ctypedef dict (*PARSE_XEVENT)(Display* display, XEvent *event)

cdef str atom_str(Display *display, Atom atom)

cdef void add_parser(unsigned int event, PARSE_XEVENT parser) noexcept
