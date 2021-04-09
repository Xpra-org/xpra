#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011-2021 Antoine Martin <antoine@xpra.org>

import time
from xpra.x11.gtk_x11.gdk_display_source import init_gdk_display_source
init_gdk_display_source()
from xpra.x11.bindings.keyboard_bindings import X11KeyboardBindings        #@UnresolvedImport
keyboard_bindings = X11KeyboardBindings()

def main():
    while True:
        down = keyboard_bindings.get_keycodes_down()
        print("down=%s" % down)
        time.sleep(1)


if __name__ == "__main__":
    main()
