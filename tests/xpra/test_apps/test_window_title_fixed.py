#!/usr/bin/env python

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  #pylint: disable=wrong-import-position


def main():
	window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
	window.set_size_request(400, 100)
	window.connect("delete_event", Gtk.main_quit)
	entry = Gtk.Entry()
	entry.set_max_length(50)
	title = "Hello"
	import sys
	if len(sys.argv)>1:
		title = sys.argv[1]
	entry.set_text("right click here to get a popup")
	entry.show()
	window.set_title(title)
	window.add(entry)
	window.show_all()
	Gtk.main()
	return 0

if __name__ == "__main__":
	main()
