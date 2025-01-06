# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import sleep, monotonic


cdef extern from "wayland-client-core.h":
    cdef struct wl_display:
        pass

    wl_display *wl_display_connect(const char *name)

    void wl_display_disconnect(wl_display *display)


# timeout is in seconds
def wait_for_wayland_display(display_name: str = "", int timeout = 10) -> None:
    cdef wl_display *d
    cdef char* name = NULL
    if display_name:
        bstr = display_name.encode("latin1")
        name = bstr
    t = 100
    cdef double start = monotonic()
    while (monotonic() - start) < timeout:
        d = wl_display_connect(name)
        if d is not NULL:
            wl_display_disconnect(d)
            return
        if t>0:
            sleep(t/1000)
            t = t//2
    raise RuntimeError(f"could not connect to wayland display {display_name!r} after {timeout} seconds")
