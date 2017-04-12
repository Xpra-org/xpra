#!/usr/bin/env python

import gtk

width = 400
height = 200

def make_win():
	window = gtk.Window(gtk.WINDOW_POPUP)
	window.set_title("Main")
	window.set_size_request(width, height)
	window.connect("delete_event", gtk.mainquit)
	window.show_all()

def main():
	make_win()
	gtk.main()


if __name__ == "__main__":
	main()
