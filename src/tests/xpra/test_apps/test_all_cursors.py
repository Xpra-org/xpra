#!/usr/bin/env python

import gobject
import gtk
from gtk import gdk
from xpra.gtk_common.cursor_names import cursor_names
names = cursor_names.keys()

width = 400
height = 200
def main():
	global names
	window = gtk.Window(gtk.WINDOW_TOPLEVEL)
	window.set_size_request(width, height)
	window.connect("delete_event", gtk.mainquit)
	label = gtk.Label()
	window.add(label)

	print("cursor names: %s" % str(names))
	def change_cursor(*args):
		global names
		name = names[0]
		names = names[1:]
		print(name)
		label.set_text(name)
		gdk_cursor = cursor_names.get(name)
		cursor = gdk.Cursor(gdk_cursor)
		window.get_window().set_cursor(cursor)
		return len(names)>0

	window.show_all()
	gobject.timeout_add(1000, change_cursor)
	gtk.main()
	return 0


if __name__ == "__main__":
	main()
