#!/usr/bin/env python

import gtk

width = 400
height = 200

def make_win(min_width=0, min_height=0, max_width=0, max_height=0):
	window = gtk.Window(gtk.WINDOW_TOPLEVEL)
	window.set_title("Size Hints Test")
	#window.set_size_request(width, height)
	window.connect("delete_event", gtk.mainquit)
	window.set_geometry_hints(window,
							min_width=min_width, min_height=min_height,
							max_width=max_width, max_height=max_height,
							base_width=100, base_height=100,
							width_inc=8, height_inc=8,
							#min_aspect=1, max_aspect=1,
							)
	window.show_all()

def main():
	make_win()
	make_win(0, 0, width, height)
	make_win(width//2, height//2)
	make_win(width//2, height//2, width*2, height*2)
	gtk.main()


if __name__ == "__main__":
	main()
