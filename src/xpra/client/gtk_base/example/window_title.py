#!/usr/bin/env python
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform import program_context
from xpra.platform.gui import force_focus
from xpra.gtk_common.gtk_util import add_close_accel

import sys
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib


def change_callback(entry, window):
	print("text=%s" % entry.get_text())
	window.set_title(entry.get_text())

def make_window():
	window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
	window.set_size_request(400, 100)
	window.connect("delete_event", Gtk.main_quit)
	entry = Gtk.Entry()
	entry.set_max_length(50)
	entry.connect("changed", change_callback, window)
	title = "Hello"

	if len(sys.argv)>1:
		title = sys.argv[1]
	entry.set_text(title)
	entry.show()
	window.add(entry)
	return window

def main():
	with program_context("window-title", "Window Title"):
		w = make_window()
		def show_with_focus():
			force_focus()
			w.show_all()
			w.present()
		add_close_accel(w, Gtk.main_quit)
		GLib.idle_add(show_with_focus)
		Gtk.main()
		return 0

if __name__ == "__main__":
	main()

