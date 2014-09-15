#!/usr/bin/env python

import gtk

def main():
	window = gtk.Window(gtk.WINDOW_TOPLEVEL)
	window.set_size_request(300, 200)
	window.set_geometry_hints(max_width=600, max_height=400)
	window.connect("delete_event", gtk.mainquit)
	window.show_all()
	gtk.main()
	return 0


if __name__ == "__main__":
	main()
