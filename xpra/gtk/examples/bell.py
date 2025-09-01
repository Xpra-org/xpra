#!/usr/bin/env python3
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform import program_context
from xpra.platform.gui import force_focus
from xpra.gtk.window import add_close_accel
from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.os_util import gi_import

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")


class BellWindow(Gtk.Window):
    def __init__(self):
        super().__init__()
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_default_size(320, 120)
        self.set_title("Test System Bell")
        self.connect("destroy", Gtk.main_quit)
        icon = get_icon_pixbuf("bell.png")
        if icon:
            self.set_icon(icon)
        btn = Gtk.Button(label="default bell")
        btn.connect('clicked', self.bell)
        self.add(btn)

    def show_with_focus(self) -> None:
        force_focus()
        self.show_all()
        super().present()

    def bell(self, *_args) -> None:
        from xpra.platform.gui import system_bell
        system_bell(self.get_window().get_xid(), 0, 100, 2000, 1000, 0, 0, "test")


def main() -> int:
    from xpra.gtk.util import quit_on_signals, init_display_source
    with program_context("bell", "Bell"):
        init_display_source()
        w = BellWindow()
        add_close_accel(w, Gtk.main_quit)
        GLib.idle_add(w.show_with_focus)
        quit_on_signals("bell test window")
        Gtk.main()
        return 0


if __name__ == "__main__":
    main()
