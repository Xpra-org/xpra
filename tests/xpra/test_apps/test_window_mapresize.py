#!/usr/bin/env python

import cairo

from gi.repository import Gtk, Gdk

WIDTH = 400
HEIGHT = 200


class MapResizeWindow(Gtk.Window):

	def __init__(self):
		Gtk.Window.__init__(self, Gtk.WINDOW_TOPLEVEL)
		self.width = WIDTH
		self.height = HEIGHT
		self.step = 0
		self.set_app_paintable(True)
		em = Gdk.EventMask
		WINDOW_EVENT_MASK = em.STRUCTURE_MASK | em.KEY_PRESS_MASK | em.KEY_RELEASE_MASK \
			| em.POINTER_MOTION_MASK | em.BUTTON_PRESS_MASK | em.BUTTON_RELEASE_MASK \
			| em.BUTTON_PRESS_MASK
		self.add_events(WINDOW_EVENT_MASK)
		self.set_size_request(self.width, self.height)
		self.connect("delete_event", Gtk.mainquit)

	def do_expose_event(self, event):
		print("do_expose_event(%s) area=%s" % (event, event.area))
		if not (self.flags() & Gtk.MAPPED):
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
		#context.rectangle(Gdk.Rectangle(0, 0, w, h))
		context.fill()

	def Xdraw(self):
		print("Xdraw() window=%s, size=%sx%s" % (self.window, self.width, self.height))
		if self.window:
			self.window.invalidate_rect(Gdk.Rectangle(0, 0, self.width, self.height), False)

	def Xresize(self, new_width, new_height):
		self.step += 1
		self.width = new_width
		self.height = new_height
		print("resizing to %s x %s" % (self.width, self.height))
		self.resize(self.width, self.height)
		self.Xdraw()
		return False


def main():
	from gi.repository import GLib
	w = MapResizeWindow()
	GLib.idle_add(w.realize)
	GLib.idle_add(w.Xresize, WIDTH/2, HEIGHT/2)
	print("window *should* (BUG!) be shown with size=%sx%s" % (WIDTH/2, HEIGHT/2))
	GLib.idle_add(w.show_all)
	GLib.timeout_add(5*1000, w.Xresize, WIDTH*2, HEIGHT*2)
	print("window should now be shown resized to=%sx%s" % (WIDTH*2, HEIGHT*2))
	Gtk.main()
	return 0


if __name__ == "__main__":
	main()

