#!/usr/bin/env python3
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import gi_import
from xpra.platform import program_context
from xpra.platform.gui import force_focus
from xpra.gtk.cursors import cursor_types
from xpra.gtk.window import add_close_accel
from xpra.gtk.pixbuf import get_icon_pixbuf

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GLib = gi_import("GLib")

width = 400
height = 200


def main() -> int:
    with program_context("cursors", "Cursors"):
        window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        window.set_title("Cursors")
        window.set_size_request(width, height)
        window.connect("delete_event", Gtk.main_quit)
        window.set_position(Gtk.WindowPosition.CENTER)
        icon = get_icon_pixbuf("pointer.png")
        if icon:
            window.set_icon(icon)
        cursor_combo = Gtk.ComboBoxText()
        cursor_combo.append_text("")
        for cursor_name in sorted(cursor_types.keys()):
            cursor_combo.append_text(cursor_name)
        window.add(cursor_combo)

        def change_cursor(*_args) -> None:
            name = cursor_combo.get_active_text()
            print("new cursor: %s" % name)
            if name:
                gdk_cursor = cursor_types.get(name)
                cursor = Gdk.Cursor(cursor_type=gdk_cursor)
            else:
                cursor = None
            window.get_window().set_cursor(cursor)

        cursor_combo.connect("changed", change_cursor)

        def show_with_focus() -> None:
            force_focus()
            window.show_all()
            window.present()

        from xpra.gtk.util import quit_on_signals
        quit_on_signals("cursors test window")
        add_close_accel(window, Gtk.main_quit)
        GLib.idle_add(show_with_focus)
        Gtk.main()
        return 0


if __name__ == "__main__":
    main()
