#!/usr/bin/env python

import gobject
gobject.threads_init()
import gtk.gdk
gtk.gdk.threads_init()

from xpra.gtk_common.cursor_names import cursor_types

width = 400
height = 200
def main():
	window = gtk.Window(gtk.WINDOW_TOPLEVEL)
	window.set_size_request(width, height)
	window.connect("delete_event", gtk.mainquit)

	names = list(cursor_types.keys())
	names = names[:2]+names[:2]+names[:2]+names[:2]+names[:2]+names[:2]+names[:2]+names[:2]+names[:2]
	def set_new_cursor():
		name = names.pop()
		cursor = gtk.gdk.Cursor(cursor_types[name])
		print("setting cursor to %s: %s" % (name, cursor))
		window.get_window().set_cursor(cursor)
		if len(names)==0:
			gtk.main_quit()
		return True

	window.show_all()
	gobject.timeout_add(5, set_new_cursor)
	gtk.main()
	return 0


if __name__ == "__main__":
	main()
