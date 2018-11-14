#!/usr/bin/env python

import gtk

width = 400
height = 200

def make_win(title=None, min_width=-1, min_height=-1, max_width=-1, max_height=-1):
	window = gtk.Window(gtk.WINDOW_TOPLEVEL)
	window.set_title(title or ("min=%s - max=%s" % ((min_width, min_height), (max_width, max_height))))
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
	make_win("tiny", 0, 0, 5, 5)
	make_win(None, 0, 0, width, height)
	make_win(None, width//2, height//2)
	make_win(None, width//2, height//2, width*2, height*2)
	gtk.main()


if __name__ == "__main__":
	main()
