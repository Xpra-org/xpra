#!/usr/bin/env python

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk	#pylint: disable=wrong-import-position

WIDTH = 400
HEIGHT = 200

def make_win(width=WIDTH, height=HEIGHT):
	window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
	window.set_title("Fixed Sized Window")
	#window.set_size_request(width, height)
	window.connect("delete_event", Gtk.main_quit)
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
	Gtk.main()


if __name__ == "__main__":
	main()
