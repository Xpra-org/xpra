#!/usr/bin/env python3
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import gi_import
from xpra.platform import program_context
from xpra.platform.gui import force_focus
from xpra.gtk.window import add_close_accel

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GLib = gi_import("GLib")

width = 400
height = 200


def make_win() -> Gtk.Window:
    window = Gtk.Window(type=Gtk.WindowType.POPUP)
    window.set_title("Main")
    window.set_size_request(width, height)
    window.set_position(Gtk.WindowPosition.CENTER)
    window.connect("delete_event", Gtk.main_quit)
    window.set_events(Gdk.EventMask.KEY_PRESS_MASK | Gdk.EventMask.BUTTON_PRESS_MASK)

    def on_press(*_args) -> None:
        Gtk.main_quit()

    window.connect("key_press_event", on_press)
    window.connect("button_press_event", on_press)
    return window


def main() -> None:
    with program_context("window-overrideredirect", "Window Override Redirect"):
        w = make_win()
        from xpra.gtk.util import quit_on_signals
        quit_on_signals("override-redirect test window")
        add_close_accel(w, Gtk.main_quit)

        def show_with_focus() -> None:
            force_focus()
            w.show_all()
            w.present()

        GLib.idle_add(show_with_focus)
        Gtk.main()


if __name__ == "__main__":
    main()
