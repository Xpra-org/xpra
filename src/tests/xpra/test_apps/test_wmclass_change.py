#!/usr/bin/env python

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib    #pylint: disable=wrong-import-position

from xpra.x11.gtk_x11.gdk_display_source import init_gdk_display_source
init_gdk_display_source()
from xpra.x11.bindings.window_bindings import X11WindowBindings  #@UnresolvedImport
from xpra.gtk_common.error import xsync
X11Window = X11WindowBindings()

def main():
    win = Gtk.Window()
    win.set_size_request(400, 100)
    win.set_title("WM_CLASS test")
    win.show()
    def change_wmclass():
        with xsync:
            X11Window.setClassHint(win.get_window().xid, "Hello", "hello")
            print("WM_CLASS changed!")
    GLib.timeout_add(1000, change_wmclass)
    Gtk.main()
    return 0


if __name__ == '__main__':
    main()
