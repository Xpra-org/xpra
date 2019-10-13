#!/usr/bin/env python
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.gtk_common.gtk_util import add_close_accel
from xpra.os_util import POSIX
if POSIX:
    from xpra.x11.gtk_x11.gdk_display_source import init_gdk_display_source
    init_gdk_display_source()

from gi.repository import Gtk


class BellWindow(Gtk.Window):
    def __init__(self):
        super().__init__()
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_default_size(320, 120)
        self.set_title("Test System Bell")
        self.connect("destroy", Gtk.main_quit)
        btn = Gtk.Button("default bell")
        btn.connect('clicked', self.bell)
        self.add(btn)
        self.show_all()
        add_close_accel(self, Gtk.main_quit)

    def bell(self, *_args):
        from xpra.platform.gui import system_bell
        system_bell(self.get_window(), 0, 100, 2000, 1000, 0, 0, "test")

def main():
    BellWindow()
    Gtk.main()
    return 0


if __name__ == "__main__":
    main()
