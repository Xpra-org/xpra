#!/usr/bin/env python

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, GLib  #pylint: disable=wrong-import-position

from xpra.x11.gtk_x11.gdk_display_source import init_gdk_display_source
from xpra.x11.gtk_x11.prop import prop_set
from xpra.gtk_common.error import xsync

def main():
    init_gdk_display_source()
    win = Gtk.Window()
    win.set_size_request(400, 100)
    win.set_title("WM_COMMAND test")
    win.show()
    def change_wmcommand():
        with xsync:
            prop_set(win.get_window(), "WM_COMMAND", "latin1", "HELLO WORLD")
            print("WM_COMMAND changed!")
    GLib.timeout_add(1000, change_wmcommand)
    Gtk.main()
    return 0


if __name__ == '__main__':
    main()
