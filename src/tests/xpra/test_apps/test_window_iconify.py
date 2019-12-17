#!/usr/bin/env python

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib	#pylint: disable=wrong-import-position

def main():
	window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
	window.set_size_request(400, 200)
	window.connect("delete_event", Gtk.main_quit)
	window.iconify()
	GLib.timeout_add(2000, window.deiconify)
	Gtk.main()
	return 0


if __name__ == "__main__":
	main()
