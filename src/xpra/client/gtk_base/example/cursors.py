#!/usr/bin/env python
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform import program_context
from xpra.platform.gui import force_focus
from xpra.gtk_common.cursor_names import cursor_types  #pylint: disable=wrong-import-position
from xpra.gtk_common.gtk_util import add_close_accel

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib  #pylint: disable=wrong-import-position


width = 400
height = 200
def main():
	with program_context("cursors", "Cursors"):
		window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
		window.set_title("Cursors")
		window.set_size_request(width, height)
		window.connect("delete_event", Gtk.main_quit)
	
		cursor_combo = Gtk.ComboBoxText()
		cursor_combo.append_text("")
		for name in sorted(cursor_types.keys()):
			cursor_combo.append_text(name)
		window.add(cursor_combo)
	
		def change_cursor(*_args):
			name = cursor_combo.get_active_text()
			print("new cursor: %s" % name)
			if name:
				gdk_cursor = cursor_types.get(name)
				cursor = Gdk.Cursor(gdk_cursor)
			else:
				cursor = None
			window.get_window().set_cursor(cursor)
	
		cursor_combo.connect("changed", change_cursor)
		def show_with_focus():
			force_focus()
			window.show_all()
			window.present()
		add_close_accel(window, Gtk.main_quit)
		GLib.idle_add(show_with_focus)
		Gtk.main()
		return 0


if __name__ == "__main__":
	main()
