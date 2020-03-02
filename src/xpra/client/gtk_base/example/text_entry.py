#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013-2020 Antoine Martin <antoine@xpra.org>

import sys

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib   #pylint: disable=wrong-import-position

from xpra.gtk_common.gtk_util import add_close_accel
from xpra.platform.gui import force_focus


def main():
    window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
    window.connect("destroy", Gtk.main_quit)
    window.set_default_size(320, 200)
    window.set_border_width(20)

    entry = Gtk.Entry()
    entry.set_text("hello")

    window.add(entry)
    add_close_accel(window, Gtk.main_quit)
    def show_with_focus():
        force_focus()
        window.show_all()
        window.present()
    GLib.idle_add(show_with_focus)
    Gtk.main()


if __name__ == "__main__":
    main()
    sys.exit(0)
