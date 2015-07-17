#!/usr/bin/env python

import gtk
from xpra.x11.gtk2 import gdk_display_source
assert gdk_display_source
from xpra.x11.gtk_x11.prop import prop_set

def main():
	window = gtk.Window(gtk.WINDOW_TOPLEVEL)
	window.set_size_request(220, 120)
	window.connect("delete_event", gtk.mainquit)
	vbox = gtk.VBox(False, 0)

	b = gtk.Button("Bypass")
	def bypass(*args):
		prop_set(window.get_window(), "_NET_WM_BYPASS_COMPOSITOR", "u32", 1)
	b.connect('clicked', bypass)
	vbox.add(b)

	b = gtk.Button("Not Bypass")
	def notbypass(*args):
		prop_set(window.get_window(), "_NET_WM_BYPASS_COMPOSITOR", "u32", 2)
	b.connect('clicked', notbypass)
	vbox.add(b)

	window.add(vbox)
	window.show_all()
	gtk.main()
	return 0


if __name__ == "__main__":
	main()
