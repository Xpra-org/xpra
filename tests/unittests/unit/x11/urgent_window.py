#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Helper for `window_test.py`: maps a window with the ICCCM `WM_HINTS` urgency flag set.

The window manager is not allowed to add its own windows to the X11 save-set,
so the window we want to manage has to belong to a different X11 client,
which means a different process.

Usage: urgent_window.py DISPLAY [urgent]
It prints the window's xid on stdout, then waits to be killed.
"""

import os
import struct
import sys
import time

# WM_HINTS flags, see ICCCM 4.1.2.4:
InputHint = 1 << 0
StateHint = 1 << 1
XUrgencyHint = 1 << 8
NormalState = 1


def wm_hints(flags: int) -> bytes:
    # flags, input, initial_state, icon_pixmap, icon_window, icon_x, icon_y, icon_mask, window_group
    return struct.pack(b"@9l", flags, 1, NormalState, 0, 0, 0, 0, 0, 0)


def main(argv) -> None:
    display = argv[1]
    urgent = len(argv) > 2 and argv[2] == "urgent"
    os.environ["DISPLAY"] = display
    from xpra.x11.bindings.display_source import X11DisplayContext
    with X11DisplayContext(display):
        from xpra.x11.bindings.core import get_root_xid, X11CoreBindings
        from xpra.x11.bindings.window import X11WindowBindings
        from xpra.x11.prop import raw_prop_set
        X11Window = X11WindowBindings()
        xid = X11Window.CreateWindow(get_root_xid(), 0, 0, 64, 64)
        flags = InputHint | StateHint | (XUrgencyHint if urgent else 0)
        raw_prop_set(xid, "WM_HINTS", "WM_HINTS", 32, wm_hints(flags))
        X11Window.MapWindow(xid)
        # the caller manages this window as soon as it sees the xid,
        # so everything must have reached the X server before we print it:
        X11CoreBindings().XSync()
        print(xid, flush=True)
        while True:
            time.sleep(60)


if __name__ == "__main__":
    main(sys.argv)
