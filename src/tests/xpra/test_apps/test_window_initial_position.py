#!/usr/bin/env python

import sys
import gtk

width = 400
height = 200

def main():
	x, y = 0, 0
	if len(sys.argv)==3:
		x, y = int(sys.argv[1]), int(sys.argv[2])
	window = gtk.Window(gtk.WINDOW_TOPLEVEL)
	window.set_size_request(width, height)
	window.connect("delete_event", gtk.mainquit)
	window.move(x, y)
	window.show_all()
	gtk.main()
		

if __name__ == "__main__":
	main()
