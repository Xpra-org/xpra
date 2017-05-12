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
							min_width=width, min_height=height,
							max_width=width, max_height=height,
							)
	window.set_resizable(False)
	window.show_all()


def main():
	import sys
	width = 1200
	height = 1024
	if len(sys.argv)==3:
		width = int(sys.argv[1])
		height = int(sys.argv[2])
	make_win(width, height)
	gtk.main()


if __name__ == "__main__":
	main()
