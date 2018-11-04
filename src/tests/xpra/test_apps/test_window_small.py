#!/usr/bin/env python

import gtk

width = 50
height = 10

def make_win(window_type=gtk.WINDOW_TOPLEVEL, min_width=-1, min_height=-1, max_width=-1, max_height=-1, decorated=True):
	window = gtk.Window(window_type)
	window.set_title("min=%s - max=%s" % ((min_width, min_height), (max_width, max_height)))
	#window.set_size_request(width, height)
	window.connect("delete_event", gtk.mainquit)
	window.set_geometry_hints(window,
							min_width=min_width, min_height=min_height,
							max_width=max_width, max_height=max_height,
							base_width=100, base_height=100,
							width_inc=8, height_inc=8,
							#min_aspect=1, max_aspect=1,
							)
	window.set_decorated(decorated)
	window.set_size_request(min_width, min_height)
	window.set_geometry_hints(None,
							min_width=min_width, min_height=min_height,
							max_width=max_width, max_height=max_height)
	window.set_resizable(min_width!=max_width or min_height!=max_height)
	window.show_all()

def main():
	make_win(gtk.WINDOW_TOPLEVEL, width, height, width, height)
	#make_win(gtk.WINDOW_TOPLEVEL, width, height, width, height, False)
	make_win(gtk.WINDOW_TOPLEVEL, width, height, -1, -1)
	#make_win(gtk.WINDOW_TOPLEVEL, width, height, -1, -1, False)
	#make_win(gtk.WINDOW_POPUP, width, height, width, height)
	gtk.main()


if __name__ == "__main__":
	main()
