#!/usr/bin/env python

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk	#pylint: disable=wrong-import-position


class TestWindow(Gtk.Window):
	def __init__(self, window_type, x=100, y=100, w=100, h=100):
		Gtk.Window.__init__(self, window_type)
		self.move(x, y)
		self.set_size_request(w, h)
		self.connect("delete_event", Gtk.main_quit)
		def hello(*_args):
			print("hello!")
		btn = Gtk.Button("hello")
		btn.connect('clicked', hello)
		vbox = Gtk.VBox()
		vbox.pack_start(btn, False, False, 20)
		self.add(vbox)
		self.show_all()

def main():
	import sys
	def intarg(n, default):
		if len(sys.argv)<(n-1):
			return default
		return int(sys.argv[n])
	x = intarg(1, 100)
	y = intarg(2, 100)
	w = intarg(3, 100)
	h = intarg(4, 100)

	#TestWindow(gtk.WINDOW_TOPLEVEL, x, y, w, h)
	TestWindow(Gtk.WindowType.POPUP, x, y, w, h)
	Gtk.main()


if __name__ == "__main__":
	main()
