#!/usr/bin/env python

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  #pylint: disable=wrong-import-position

width = 400
height = 200

def make_win():
	window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
	window.set_title("Main")
	window.set_size_request(width, height)
	window.connect("delete_event", Gtk.main_quit)
	window.show_all()

def main():
	make_win()
	Gtk.main()


if __name__ == "__main__":
	main()
