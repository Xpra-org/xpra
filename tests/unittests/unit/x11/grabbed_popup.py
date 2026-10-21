#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Hold both grabs on a popup, or probe them, using a separate X11 connection."""

import os
import sys
import time


def main() -> None:
    os.environ["DISPLAY"] = sys.argv[1]
    os.environ["GDK_BACKEND"] = "x11"
    from xpra.os_util import gi_import
    from xpra.util.env import IgnoreWarningsContext
    Gtk = gi_import("Gtk")
    Gdk = gi_import("Gdk")
    gi_import("GdkX11")
    window = Gtk.Window(type=Gtk.WindowType.POPUP)
    window.set_default_size(64, 64)
    window.show_all()
    gdkwin = window.get_window()
    with IgnoreWarningsContext():
        pointer = Gdk.pointer_grab(gdkwin, False, Gdk.EventMask.BUTTON_PRESS_MASK, None, None, Gdk.CURRENT_TIME)
        keyboard = Gdk.keyboard_grab(gdkwin, False, Gdk.CURRENT_TIME)
    Gdk.Display.get_default().sync()
    print(gdkwin.get_xid(), int(pointer), int(keyboard), flush=True)
    if len(sys.argv) > 2 and sys.argv[2] == "probe":
        return
    # Deliberately ignore input and never ungrab, even after being unmapped.
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
