#!/usr/bin/env python

import gtk
import pango
import gobject
import cairo

WIDTH = 800
HEIGHT = 600

class VideoRegionsWindow(gtk.Window):

	def __init__(self):
		gtk.Window.__init__(self, gtk.WINDOW_TOPLEVEL)
		self.width = WIDTH
		self.height = HEIGHT
		self.step = 0
		self.set_size_request(self.width, self.height)

		self.hbox = gtk.HBox()
		self.add(self.hbox)

		self.darea = gtk.DrawingArea()
		self.darea.connect("expose-event", self.expose)
		self.hbox.pack_start(self.darea, True, True, 20)

		self.vbox = gtk.VBox()
		self.hbox.pack_start(self.vbox, False, False, 20)

		self.label = gtk.Label("hello world")
		self.label.modify_font(pango.FontDescription("serif 20"))
		self.vbox.add(self.label)

		self.button = gtk.Button("Some Button")
		self.vbox.add(self.button)

		self.connect("delete_event", gtk.mainquit)
		self.show_all()

	def expose(self, widget, event):
		print("expose(%s, %s) area=%s" % (widget, event, event.area))
		if not (self.flags() & gtk.MAPPED):
			return
		context = widget.window.cairo_create()
		context.rectangle(event.area)
		context.clip()
		context.set_operator(cairo.OPERATOR_OVER)
		v = (self.step % 10)/10.0
		context.set_source_rgba(v, 0.8, v, 0.8)
		context.rectangle(event.area)
		#w, h = self._size
		#context.rectangle(gdk.Rectangle(0, 0, w, h))
		context.fill()

	def redraw(self):
		self.step += 1
		self.darea.queue_draw()
		sm = 4
		if self.step%sm==0:
			self.label.set_text("Step = %s" % (self.step/sm))
		hm = 8
		if self.step%hm==0:
			self.button.set_label("Hello %s" % (self.step/hm))
		fr = 20
		if self.step%fr==0:
			self.redraw()
		return True


def main():
	w = VideoRegionsWindow()
	gobject.timeout_add(10, w.redraw)
	gtk.main()
	return 0


if __name__ == "__main__":
	main()

