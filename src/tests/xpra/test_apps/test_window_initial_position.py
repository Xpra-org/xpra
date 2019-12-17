#!/usr/bin/env python

import sys
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk	#pylint: disable=wrong-import-position

width = 400
height = 200

def main():
	x, y = 0, 0
	if len(sys.argv)==3:
		x, y = int(sys.argv[1]), int(sys.argv[2])
	window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
	window.set_size_request(width, height)
	window.connect("delete_event", Gtk.main_quit)
	window.realize()
	window.move(x, y)
	from xpra.x11.gtk_x11.gdk_display_source import init_gdk_display_source
	init_gdk_display_source()
	from xpra.x11.bindings.window_bindings import X11WindowBindings
	hints = {"position" : (x, y)}
	X11WindowBindings().setSizeHints(window.get_window().xid, hints)
	window.show_all()
	Gtk.main()


if __name__ == "__main__":
	main()
