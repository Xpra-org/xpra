#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform import program_context
from xpra.platform.gui import force_focus
from xpra.gtk_common.gtk_util import add_close_accel

import sys
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib   #pylint: disable=wrong-import-position


def make_window():
    window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
    window.set_title("Text Entry")
    window.connect("destroy", Gtk.main_quit)
    window.set_default_size(320, 200)
    window.set_border_width(20)

    entry = Gtk.Entry()
    entry.set_text("hello")

    window.add(entry)
    return window

def main():
    with program_context("text-entry", "Text Entry"):
        w = make_window()
        add_close_accel(w, Gtk.main_quit)
        def show_with_focus():
            force_focus()
            w.show_all()
            w.present()
        GLib.idle_add(show_with_focus)
        Gtk.main()


if __name__ == "__main__":
    main()
    sys.exit(0)
