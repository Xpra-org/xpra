#!/usr/bin/env python

import gtk

WIDTH = 400
HEIGHT = 200

def make_win(width=WIDTH, height=HEIGHT):
	window = gtk.Window(gtk.WINDOW_TOPLEVEL)
	window.set_title("Fixed Sized Window")
	#window.set_size_request(width, height)
	window.connect("delete_event", gtk.mainquit)
	window.set_geometry_hints(window,
							min_width=WIDTH, min_height=HEIGHT,
							max_width=WIDTH, max_height=HEIGHT,
							)
	window.set_resizable(False)
	window.show_all()

def main():
	make_win()
	gtk.main()


if __name__ == "__main__":
	main()
