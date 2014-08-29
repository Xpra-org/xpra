#!/usr/bin/env python

import gtk

width = 400
height = 200
def main():
	window = gtk.Window(gtk.WINDOW_TOPLEVEL)
	window.set_size_request(width, height)
	window.connect("delete_event", gtk.mainquit)
	window.move(0, 0)
	window.show_all()
	gtk.main()
	return 0


if __name__ == "__main__":
	main()
