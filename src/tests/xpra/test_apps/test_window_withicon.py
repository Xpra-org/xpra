#!/usr/bin/env python

import os
import gtk

def main():
	window = gtk.Window(gtk.WINDOW_TOPLEVEL)
	window.set_size_request(400, 200)
	window.connect("delete_event", gtk.mainquit)
	for x in ("/usr/share/icons/gnome/48x48/emblems/emblem-important.png", "/opt/share/icons/xpra.png"):
		if os.path.exists(x):
			print("using %s" % x)
			window.set_icon_from_file(x)
			break
	window.show_all()
	gtk.main()
	return 0


if __name__ == "__main__":
	main()
