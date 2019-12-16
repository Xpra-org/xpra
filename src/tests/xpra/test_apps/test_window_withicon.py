#!/usr/bin/env python

import os

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk


def main():
	window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
	window.set_size_request(400, 200)
	window.connect("delete_event", Gtk.main_quit)
	for x in ("/usr/share/icons/gnome/48x48/emblems/emblem-important.png", "/opt/share/icons/xpra.png"):
		if os.path.exists(x):
			print("using %s" % x)
			window.set_icon_from_file(x)
			break
	window.show_all()
	Gtk.main()
	return 0


if __name__ == "__main__":
	main()
