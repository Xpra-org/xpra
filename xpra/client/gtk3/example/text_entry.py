#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2013-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform import program_context
from xpra.platform.gui import force_focus
from xpra.gtk_common.gtk_util import add_close_accel, get_icon_pixbuf

import sys
import gi
gi.require_version("Gtk", "3.0")  # @UndefinedVariable
from gi.repository import Gtk, GLib   #pylint: disable=wrong-import-position @UnresolvedImport


def make_window():
    window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
    window.set_title("Text Entry")
    window.connect("destroy", Gtk.main_quit)
    window.set_default_size(320, -1)
    window.set_border_width(40)
    window.set_position(Gtk.WindowPosition.CENTER)
    icon = get_icon_pixbuf("font.png")
    if icon:
        window.set_icon(icon)

    vbox = Gtk.VBox(homogeneous=False, spacing=10)
    entry = Gtk.Entry()
    entry.set_text("hello")
    vbox.add(entry)

    textview = Gtk.TextView()
    textbuffer = textview.get_buffer()
    textbuffer.set_text("Sample text\nmultiline")
    textview.set_editable(True)
    textview.set_size_request(200, 80)
    vbox.add(textview)

    window.add(vbox)
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
        def signal_handler(*_args):
            GLib.idle_add(Gtk.main_quit)
        from xpra.gtk_common.gobject_compat import register_os_signals
        register_os_signals(signal_handler)
        Gtk.main()


if __name__ == "__main__":
    main()
    sys.exit(0)
