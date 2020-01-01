#!/usr/bin/env python

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk  #pylint: disable=wrong-import-position

width = 400
height = 200

def make_win():
	window = Gtk.Window(type=Gtk.WindowType.POPUP)
	window.set_title("Main")
	window.set_size_request(width, height)
	window.connect("delete_event", Gtk.main_quit)
	window.set_events(Gdk.EventMask.KEY_PRESS_MASK | Gdk.EventMask.BUTTON_PRESS_MASK)
	def on_press(*_args):
		Gtk.main_quit()
	window.connect("key_press_event", on_press)
	window.connect("button_press_event", on_press)
	window.show_all()

def main():
	make_win()
	Gtk.main()


if __name__ == "__main__":
	main()
