#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject
gobject.threads_init()
import gtk

from xpra.x11.gtk2 import gdk_display_source
assert gdk_display_source
from xpra.x11.xroot_props import XRootPropWatcher


def main():
    ROOT_PROPS = ["RESOURCE_MANAGER", "_NET_WORKAREA"]
    root = gtk.gdk.get_default_root_window()
    xrpw = XRootPropWatcher(ROOT_PROPS, root)
    gobject.timeout_add(1000, xrpw.notify_all)
    try:
        gtk.main()
    finally:
        xrpw.cleanup()


if __name__ == "__main__":
    main()
