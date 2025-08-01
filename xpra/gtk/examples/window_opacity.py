#!/usr/bin/env python3
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import gi_import
from xpra.platform import program_context
from xpra.platform.gui import force_focus
from xpra.gtk.window import add_close_accel
from xpra.gtk.pixbuf import get_icon_pixbuf

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")

opacity = 50


def make_window() -> Gtk.Window:
    win = Gtk.Window()
    win.set_position(Gtk.WindowPosition.CENTER)
    win.set_title('Opacity Test')
    win.connect('delete-event', Gtk.main_quit)
    icon = get_icon_pixbuf("windows.png")
    if icon:
        win.set_icon(icon)

    btn = Gtk.Button(label="Change Opacity")

    def change_opacity(*_args) -> None:
        global opacity
        opacity = (opacity + 5) % 100
        btn.set_label(f"Change Opacity: {opacity}%")
        win.set_opacity(opacity / 100.0)

    btn.connect('clicked', change_opacity)
    win.add(btn)
    change_opacity()
    return win


def main() -> int:
    with program_context("window-opacity", "Window Opacity"):
        w = make_window()

        def show_with_focus() -> None:
            force_focus()
            w.show_all()
            w.present()

        add_close_accel(w, Gtk.main_quit)
        from xpra.gtk.util import quit_on_signals
        quit_on_signals("window opacity test window")
        GLib.idle_add(show_with_focus)
        Gtk.main()
        return 0


if __name__ == '__main__':
    main()
