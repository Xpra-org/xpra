#!/usr/bin/env python

import gtk
from gtk import gdk
import gobject
import cairo

WIDTH = 400
HEIGHT = 200

class MapResizeWindow(gtk.Window):

	def __init__(self):
		gtk.Window.__init__(self, gtk.WINDOW_TOPLEVEL)
		self.width = WIDTH
		self.height = HEIGHT
		self.step = 0
		self.set_app_paintable(True)
		WINDOW_EVENT_MASK = gdk.STRUCTURE_MASK | gdk.KEY_PRESS_MASK | gdk.KEY_RELEASE_MASK \
			| gdk.POINTER_MOTION_MASK | gdk.BUTTON_PRESS_MASK | gdk.BUTTON_RELEASE_MASK \
			| gdk.PROPERTY_CHANGE_MASK
		self.add_events(WINDOW_EVENT_MASK)
		self.set_size_request(self.width, self.height)
		self.connect("delete_event", gtk.mainquit)

	def do_expose_event(self, event):
		print("do_expose_event(%s) area=%s" % (event, event.area))
		if not (self.flags() & gtk.MAPPED):
			print("do_expose_event(%s) window not mapped yet!")
			return
		context = self.window.cairo_create()
		context.rectangle(event.area)
		context.clip()
		context.set_operator(cairo.OPERATOR_OVER)
		v = (self.step % 10)/10.0
		context.set_source_rgba(v, 0.8, v, 0.8)
		context.rectangle(event.area)
		#w, h = self._size
		#context.rectangle(gdk.Rectangle(0, 0, w, h))
		context.fill()

	def Xdraw(self):
		print("Xdraw() window=%s, size=%sx%s" % (self.window, self.width, self.height))
		if self.window:
			self.window.invalidate_rect(gdk.Rectangle(0, 0, self.width, self.height), False)
	
	def Xresize(self, *args):
		self.step += 1
		self.width = WIDTH+20*(self.step % 20)
		self.height = HEIGHT+20*(self.step % 20)
		print("resizing to %s x %s" % (self.width, self.height))
		self.resize(self.width, self.height)
		self.Xdraw()
		return False

gobject.type_register(MapResizeWindow)


def main():
	w = MapResizeWindow()
	gobject.idle_add(w.realize)
	gobject.idle_add(w.Xresize)
	gobject.idle_add(w.show_all)
	gobject.idle_add(w.Xresize)
	gobject.timeout_add(10*1000, gtk.mainquit)
	gtk.main()
	return 0


if __name__ == "__main__":
	main()

