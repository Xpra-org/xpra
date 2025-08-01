#!/usr/bin/env python3
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from xpra.os_util import gi_import
from xpra.platform import program_context
from xpra.platform.gui import force_focus
from xpra.gtk.window import add_close_accel
from xpra.gtk.pixbuf import get_icon_pixbuf

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")


def change_callback(entry, window) -> None:
    print("text=%s" % entry.get_text())
    window.set_title(entry.get_text())


def make_window() -> Gtk.Window:
    window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
    window.set_size_request(400, 100)
    window.set_position(Gtk.WindowPosition.CENTER)
    window.connect("delete_event", Gtk.main_quit)
    icon = get_icon_pixbuf("font.png")
    if icon:
        window.set_icon(icon)
    entry = Gtk.Entry()
    entry.set_max_length(50)
    entry.connect("changed", change_callback, window)
    title = "Hello"

    if len(sys.argv) > 1:
        title = sys.argv[1]
    entry.set_text(title)
    entry.show()
    window.add(entry)
    return window


def main() -> int:
    with program_context("window-title", "Window Title"):
        w = make_window()
        add_close_accel(w, Gtk.main_quit)
        from xpra.gtk.util import quit_on_signals
        quit_on_signals("title test window")

        def show_with_focus() -> None:
            force_focus()
            w.show_all()
            w.present()

        GLib.idle_add(show_with_focus)
        Gtk.main()
        return 0


if __name__ == "__main__":
    main()
