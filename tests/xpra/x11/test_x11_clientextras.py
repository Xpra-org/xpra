#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject
gobject.threads_init()
import gtk


from xpra.platform.xposix.gui import ClientExtras
from xpra.x11.gtk2 import gdk_display_source
assert gdk_display_source


class FakeClient(object):
    def __init__(self):
        self.xsettings_tuple = True
        self.xsettings_enabled = True
    def connect(self, *args):
        print("connect(%s)" % str(args))
    def send(self, *args):
        print("send(%s)" % str(args))
    def screen_size_changed(self, *args):
        print("screen_size_changed(%s)" % str(args))

def main():
    fc = FakeClient()
    ce = ClientExtras(fc)
    gobject.timeout_add(1000, ce.do_setup_xprops)
    try:
        gtk.main()
    finally:
        ce.cleanup()


if __name__ == "__main__":
    main()
