#!/usr/bin/env python

import gtk

def change_callback(self, window, entry):
	print("text=%s" % entry.get_text())
	window.set_title(entry.get_text())

def main():
	window = gtk.Window(gtk.WINDOW_TOPLEVEL)
	window.set_size_request(400, 100)
	window.connect("delete_event", gtk.mainquit)
	entry = gtk.Entry()
	entry.set_max_length(50)
	entry.connect("changed", change_callback, window, entry)
	entry.set_text("Hello")
	entry.show()
	window.add(entry)
	window.show_all()
	gtk.main()
	return 0

if __name__ == "__main__":
	main()

