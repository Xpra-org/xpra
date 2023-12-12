#!/usr/bin/env python3
# Copyright (C) 2017-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform import program_context
from xpra.platform.gui import force_focus
from xpra.gtk_common.gtk_util import add_close_accel, get_icon_pixbuf

import gi
gi.require_version("Gtk", "3.0")  # @UndefinedVariable
from gi.repository import Gtk, GLib  # @UnresolvedImport


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

    def show_with_focus(self):
        force_focus()
        self.show_all()
        super().present()

    def bell(self, *_args):
        from xpra.platform.gui import system_bell
        system_bell(self.get_window(), 0, 100, 2000, 1000, 0, 0, "test")

def main():
    from xpra.gtk_common.gobject_compat import register_os_signals
    from xpra.gtk_common.gtk_util import init_display_source
    with program_context("bell", "Bell"):
        init_display_source()
        w = BellWindow()
        add_close_accel(w, Gtk.main_quit)
        GLib.idle_add(w.show_with_focus)
        def signal_handler(_signal):
            GLib.idle_add(Gtk.main_quit)
        register_os_signals(signal_handler)
        Gtk.main()
        return 0


if __name__ == "__main__":
    main()
