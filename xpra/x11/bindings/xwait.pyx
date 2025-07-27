# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import signal
import threading

from xpra.x11.bindings.xlib cimport (
    Display, XOpenDisplay,
    XNextEvent, XEvent, XErrorEvent,
    XSetIOErrorHandler, XSetErrorHandler,
)


cdef int exit_code = -1
exit_event = threading.Event()


def err(s) -> None:
    try:
        sys.stderr.write("%s\n"  % s)
        sys.stderr.flush()
    except IOError:
        pass


cdef void end(msg, int code = exit_code) noexcept:
    global exit_code, exit_event
    err(msg)
    exit_code = code
    exit_event.set()


cdef int x11_io_error_handler(Display *display) except 0:
    global message
    message = b"X11 fatal IO error"
    exit_code = 0
    return 0


cdef int x11_error_handler(Display *display, XErrorEvent *event) except 0:
    #X11 error handler called (ignored)
    return 0


SIGNAMES = {}
for signame in (sig for sig in dir(signal) if sig.startswith("SIG") and not sig.startswith("SIG_")):
    SIGNAMES[getattr(signal, signame)] = signame


def os_signal(signum, _frame=None) -> None:
    end("\ngot signal %s" % SIGNAMES.get(signum, signum), 128-signum)


def xwait(display_name: str="") -> None:
    global exit_code
    if not display_name:
        end("no display specified", 1)
        return
    bname = display_name.encode()
    cdef char* name = bname
    cdef Display * d = XOpenDisplay(name)
    if d==NULL:
        end("failed to open display %r" % (display_name, ), 1)
        return
    #we have successfully connected to the display,
    #so from now on return success on exit:
    XSetErrorHandler(&x11_error_handler)
    XSetIOErrorHandler(&x11_io_error_handler)
    cdef XEvent e
    while True:
        with nogil:
            XNextEvent(d, &e)


def main(args):
    signal.signal(signal.SIGINT, os_signal)
    signal.signal(signal.SIGTERM, os_signal)

    display_name = os.environ.get("DISPLAY", "") if not args else args[0]
    args = (display_name, )
    t = threading.Thread(target=xwait, name="xwait", args=args, daemon=True)
    t.start()

    exit_event.wait()
    sys.exit(exit_code)
