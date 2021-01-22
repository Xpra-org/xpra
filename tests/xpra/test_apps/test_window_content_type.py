#!/usr/bin/env python

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk	#pylint: disable=wrong-import-position

from xpra.x11.gtk_x11.gdk_display_source import init_gdk_display_source
init_gdk_display_source()


def change_callback(self, window, entry):
	print("content_type=%s" % entry.get_text())
	if window.get_window():
		from xpra.x11.gtk_x11.prop import prop_set
		prop_set(window.get_window(), "_XPRA_CONTENT_TYPE", "latin1", entry.get_text().decode())

def main():
	window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
	window.set_size_request(400, 100)
	window.connect("delete_event", Gtk.main_quit)
	entry = Gtk.Entry()
	entry.set_max_length(50)
	entry.connect("changed", change_callback, window, entry)
	content_type = "text"
	import sys
	if len(sys.argv)>1:
		content_type = sys.argv[1]
	entry.set_text(content_type)
	entry.show()
	window.add(entry)
	window.show_all()
	Gtk.main()
	return 0

if __name__ == "__main__":
	main()

