#!/usr/bin/env python

from xpra.gtk_common.gobject_compat import import_gtk
from xpra.gtk_common.gtk_util import WINDOW_POPUP

gtk = import_gtk()


class TestWindow(gtk.Window):
	def __init__(self, window_type, x=100, y=100, w=100, h=100):
		gtk.Window.__init__(self, window_type)
		self.move(x, y)
		self.set_size_request(100, 100)
		self.connect("delete_event", gtk.main_quit)
		def hello(*args):
			print("hello!")
		btn = gtk.Button("hello")
		btn.connect('clicked', hello)
		vbox = gtk.VBox()
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
	TestWindow(WINDOW_POPUP, x, y, w, h)
	gtk.main()


if __name__ == "__main__":
	main()
