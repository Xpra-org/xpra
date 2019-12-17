#!/usr/bin/env python

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk   #pylint: disable=wrong-import-position
from xpra.gtk_common.gtk_util import get_root_size

width = 400
height = 200
def main():
	window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
	window.set_size_request(width, height)
	window.connect("delete_event", Gtk.main_quit)
	vbox = Gtk.VBox(False, 0)
	hbox = Gtk.HBox(False, 0)
	vbox.pack_start(hbox, expand=False, fill=False, padding=10)
	btn = Gtk.Button("move me")
	hbox.pack_start(btn, expand=False, fill=False, padding=10)
	def move(*_args):
		x, y = window.get_position()
		maxx, maxy = get_root_size()
		new_x = (x+100) % maxx
		new_y = (y+100) % maxy
		print("moving to %s x %s" % (new_x, new_y))
		window.move(new_x, new_y)
	btn.connect('clicked', move)
	window.add(vbox)
	window.show_all()
	Gtk.main()
	return 0


if __name__ == "__main__":
	main()
