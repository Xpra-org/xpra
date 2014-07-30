#!/usr/bin/env python


import gtk
from gtk import gdk
from xpra.gtk_common.cursor_names import cursor_types

width = 400
height = 200
def main():
	window = gtk.Window(gtk.WINDOW_TOPLEVEL)
	window.set_size_request(width, height)
	window.connect("delete_event", gtk.mainquit)

	cursor_combo = gtk.combo_box_new_text()
	cursor_combo.append_text("")
	for name in sorted(cursor_types.keys()):
		cursor_combo.append_text(name)
	window.add(cursor_combo)

	def change_cursor(*args):
		name = cursor_combo.get_active_text()
		print(name)
		gdk_cursor = cursor_types.get(name)
		cursor = gdk.Cursor(gdk_cursor)
		window.get_window().set_cursor(cursor)

	cursor_combo.connect("changed", change_cursor)
	window.show_all()
	gtk.main()
	return 0


if __name__ == "__main__":
	main()
