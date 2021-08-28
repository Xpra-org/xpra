# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2017-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Special guard to work around Fedora/RH's pygtk2 silliness
# see http://partiwm.org/ticket/34 for details

from time import sleep
from xpra.os_util import bytestostr
from xpra.monotonic_time cimport monotonic_time  #pylint: disable=syntax-error

cdef extern from "X11/Xlib.h":
    ctypedef struct Display:
        pass
    Display * XOpenDisplay(char * name)
    int XCloseDisplay(Display * xdisplay)


# timeout is in seconds
def wait_for_x_server(display_name, int timeout):
    cdef Display * d
    cdef char* name
    if display_name is not None:
        name = display_name
    else:
        name = NULL
    t = 100
    cdef double start = monotonic_time()
    while (monotonic_time() - start) < timeout:
        d = XOpenDisplay(name)
        if d is not NULL:
            XCloseDisplay(d)
            return
        if t>0:
            sleep(t/1000)
            t = t//2
    raise RuntimeError("could not connect to X server on display '%s' after %i seconds" % (bytestostr(display_name), timeout))
