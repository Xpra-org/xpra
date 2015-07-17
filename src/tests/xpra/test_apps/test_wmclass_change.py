#!/usr/bin/env python

import gobject
import pygtk
pygtk.require('2.0')
import gtk

from xpra.x11.gtk2 import gdk_display_source
assert gdk_display_source
from xpra.x11.bindings.window_bindings import X11WindowBindings  #@UnresolvedImport
from xpra.gtk_common.error import xsync
X11Window = X11WindowBindings()

def main():
    win = gtk.Window()
    win.set_size_request(400, 100)
    win.set_title("WM_CLASS test")
    win.show()
    def change_wmclass():
        with xsync:
            X11Window.setClassHint(win.get_window().xid, "Hello", "hello")
            print("WM_CLASS changed!")
    gobject.timeout_add(1000, change_wmclass)
    gtk.main()
    return 0


if __name__ == '__main__':
    main()
