#!/usr/bin/env python3

from xpra.os_util import gi_import

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")


def main():
    from xpra.x11.gtk.display_source import init_gdk_display_source
    init_gdk_display_source()

    from xpra.x11.bindings.classhint import XClassHintBindings  # @UnresolvedImport
    from xpra.x11.error import xsync
    XClassHint = XClassHintBindings()

    win = Gtk.Window()
    win.set_size_request(400, 100)
    win.set_title("WM_CLASS test")
    win.show()

    def change_wmclass():
        with xsync:
            XClassHint.setClassHint(win.get_window().get_xid(), "Hello", "hello")
            print("WM_CLASS changed!")

    GLib.timeout_add(1000, change_wmclass)
    Gtk.main()
    return 0


if __name__ == '__main__':
    main()
