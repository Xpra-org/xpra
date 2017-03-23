# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Special guard to work around Fedora/RH's pygtk2 silliness
# see http://partiwm.org/ticket/34 for details

from time import sleep
from xpra.os_util import monotonic_time

cdef extern from "X11/Xlib.h":
    ctypedef struct Display:
        pass
    Display * XOpenDisplay(char * name)
    int XCloseDisplay(Display * xdisplay)


# timeout is in seconds
def wait_for_x_server(display_name, int timeout):
    cdef Display * d
    cdef char* name
    start = monotonic_time()
    name = display_name
    first_time = True
    while first_time or (monotonic_time() - start) < timeout:
        if not first_time:
            sleep(0.2)
        first_time = False
        d = XOpenDisplay(name)
        if d is not NULL:
            XCloseDisplay(d)
            return
    raise RuntimeError("could not connect to X server on display '%s' after %i seconds" % (display_name, timeout))
