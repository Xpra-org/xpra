#!/usr/bin/env python

import gtk
from gtk import gdk
import cairo
import gobject

CRASH = True

class ClientWindow(gtk.Window):

	def __init__(self, w, h):
		gtk.Window.__init__(self, gtk.WINDOW_TOPLEVEL)
		self.set_size_request(w, h)
		self.set_app_paintable(True)
		self.add_events(gdk.STRUCTURE_MASK)
		self._backing = None
		self.new_backing(w, h)

	def new_backing(self, w, h):
		print("new_backing(%s, %s)" % (w, h))
		if self._backing is None:
			self._backing = Backing()
		self._backing.init(w, h)

	def do_configure_event(self, event):
		print("do_configure_event(%s)" % event)
		gtk.Window.do_configure_event(self, event)
		_, _, w, h, _ = self.get_window().get_geometry()
		self.new_backing(w, h)


class Backing(object):

	def __init__(self):
		self._backing = None

	def init(self, w, h):
		old_backing = self._backing
		self._backing = gdk.Pixmap(gdk.get_default_root_window(), w, h)
		cr = self._backing.cairo_create()
		cr.set_source_rgb(1, 1, 1)
		if CRASH and old_backing is not None:
			cr.set_operator(cairo.OPERATOR_SOURCE)
			cr.set_source_pixmap(old_backing, 0, 0)
			cr.paint()
			old_w, old_h = old_backing.get_size()
			if w>old_w:
				cr.new_path()
				cr.move_to(old_w, 0)
				cr.line_to(w, 0)
				cr.line_to(w, h)
				cr.line_to(old_w, h)
				cr.close_path()
				cr.fill()
			if h>old_h:
				cr.new_path()
				cr.move_to(0, old_h)
				cr.line_to(0, h)
				cr.line_to(w, h)
				cr.line_to(w, old_h)
				cr.close_path()
				cr.fill()
		else:
			cr.rectangle(0, 0, w, h)
			cr.fill()

gobject.type_register(ClientWindow)


def main():
	window = ClientWindow(400, 200)
	window.show()
	gtk.main()


if __name__ == "__main__":
	main()
