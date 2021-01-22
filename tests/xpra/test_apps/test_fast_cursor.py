#!/usr/bin/env python

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib

from xpra.gtk_common.cursor_names import cursor_types

width = 400
height = 200
def main():
	window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
	window.set_size_request(width, height)
	window.connect("delete_event", Gtk.main_quit)

	names = list(cursor_types.keys())
	names = names[:2]+names[:2]+names[:2]+names[:2]+names[:2]+names[:2]+names[:2]+names[:2]+names[:2]
	def set_new_cursor():
		name = names.pop()
		cursor = Gdk.Cursor(cursor_types[name])
		print("setting cursor to %s: %s" % (name, cursor))
		window.get_window().set_cursor(cursor)
		if len(names)==0:
			Gtk.main_quit()
		return True

	window.show_all()
	GLib.timeout_add(5, set_new_cursor)
	Gtk.main()
	return 0


if __name__ == "__main__":
	main()
