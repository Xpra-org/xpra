#!/usr/bin/env python

import glib
import gtk

def main():
	window = gtk.Window(gtk.WINDOW_TOPLEVEL)
	window.set_size_request(400, 200)
	window.connect("delete_event", gtk.mainquit)
	window.iconify()
	glib.timeout_add(2000, window.deiconify)
	gtk.main()
	return 0


if __name__ == "__main__":
	main()
