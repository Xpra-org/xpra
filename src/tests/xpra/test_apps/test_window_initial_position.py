#!/usr/bin/env python

import sys
import gtk

width = 400
height = 200

def main():
	x, y = 0, 0
	if len(sys.argv)==3:
		x, y = int(sys.argv[1]), int(sys.argv[2])
	window = gtk.Window(gtk.WINDOW_TOPLEVEL)
	window.set_size_request(width, height)
	window.connect("delete_event", gtk.mainquit)
	window.realize()
	window.move(x, y)
	from xpra.x11.gtk2.gdk_display_source import display
	assert display
	from xpra.x11.bindings.window_bindings import X11WindowBindings
	hints = {"position" : (x, y)}
	X11WindowBindings().setSizeHints(window.get_window().xid, hints)
	window.show_all()
	gtk.main()


if __name__ == "__main__":
	main()
