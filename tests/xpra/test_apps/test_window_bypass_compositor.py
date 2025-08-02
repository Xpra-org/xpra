#!/usr/bin/env python3

from xpra.os_util import gi_import
from xpra.x11.gtk.display_source import init_gdk_display_source
from xpra.x11.prop import prop_set


def main():
    init_gdk_display_source()
    Gtk = gi_import("Gtk")

    window = Gtk.Window()
    window.set_size_request(220, 120)
    window.connect("delete_event", Gtk.main_quit)
    vbox = Gtk.VBox(homogeneous=False, spacing=0)

    b = Gtk.Button(label="Bypass")

    def bypass(*_args) -> None:
        prop_set(window.get_window(), "_NET_WM_BYPASS_COMPOSITOR", "u32", 1)

    b.connect('clicked', bypass)
    vbox.add(b)

    b = Gtk.Button(label="Not Bypass")

    def notbypass(*_args) -> None:
        prop_set(window.get_window(), "_NET_WM_BYPASS_COMPOSITOR", "u32", 2)

    b.connect('clicked', notbypass)
    vbox.add(b)

    window.add(vbox)
    window.show_all()
    Gtk.main()
    return 0


if __name__ == "__main__":
    main()
