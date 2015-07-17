#!/usr/bin/env python

import gobject
import pygtk
pygtk.require('2.0')
import gtk

from xpra.x11.gtk2 import gdk_display_source
assert gdk_display_source
from xpra.x11.gtk_x11.prop import prop_set
from xpra.gtk_common.error import xsync

def main():
    win = gtk.Window()
    win.set_size_request(400, 100)
    win.set_title("WM_COMMAND test")
    win.show()
    def change_wmcommand():
        with xsync:
            prop_set(win.get_window(), "WM_COMMAND", "latin1", u"HELLO WORLD")
            print("WM_COMMAND changed!")
    gobject.timeout_add(1000, change_wmcommand)
    gtk.main()
    return 0


if __name__ == '__main__':
    main()
