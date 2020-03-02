#!/usr/bin/env python
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib   #pylint: disable=wrong-import-position

from xpra.gtk_common.gtk_util import add_close_accel
from xpra.platform.gui import force_focus


opacity = 50

def main():
    win = Gtk.Window()

    win.set_title('Alpha Demo')
    win.connect('delete-event', Gtk.main_quit)

    btn = Gtk.Button(label="Change Opacity")
    def change_opacity(*_args):
        global opacity
        opacity = (opacity + 5) % 100
        btn.set_label("Change Opacity: %i%%" % opacity)
        win.set_opacity(opacity/100.0)
    btn.connect('clicked', change_opacity)
    win.add(btn)
    change_opacity()

    def show_with_focus():
        force_focus()
        win.show_all()
        win.present()
    add_close_accel(win, Gtk.main_quit)
    GLib.idle_add(show_with_focus)
    Gtk.main()
    return 0


if __name__ == '__main__':
    main()
