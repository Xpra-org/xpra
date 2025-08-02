#!/usr/bin/env python3

from xpra.os_util import gi_import
from xpra.x11.gtk.display_source import init_gdk_display_source
from xpra.x11.prop import prop_set
from xpra.x11.error import xsync

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GLib = gi_import("GLib")


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
