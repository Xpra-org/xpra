#!/usr/bin/env python

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk   #pylint: disable=wrong-import-position
from xpra.x11.gtk_x11.gdk_display_source import init_gdk_display_source
init_gdk_display_source()
from xpra.x11.gtk_x11.prop import prop_set

def main():
	window = Gtk.Window()
	window.set_size_request(220, 120)
	window.connect("delete_event", Gtk.main_quit)
	vbox = Gtk.VBox(False, 0)

	b = Gtk.Button(label="Bypass")
	def bypass(*args):
		prop_set(window.get_window(), "_NET_WM_BYPASS_COMPOSITOR", "u32", 1)
	b.connect('clicked', bypass)
	vbox.add(b)

	b = Gtk.Button(label="Not Bypass")
	def notbypass(*args):
		prop_set(window.get_window(), "_NET_WM_BYPASS_COMPOSITOR", "u32", 2)
	b.connect('clicked', notbypass)
	vbox.add(b)

	window.add(vbox)
	window.show_all()
	Gtk.main()
	return 0


if __name__ == "__main__":
	main()
