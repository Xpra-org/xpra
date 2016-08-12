#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>

import sys
import pygtk
pygtk.require('2.0')
import gtk
import gobject


class TestForm(object):

	def	__init__(self):
		self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
		self.window.connect("destroy", gtk.main_quit)
		self.window.set_default_size(320, 200)
		self.window.set_border_width(20)

		vbox = gtk.VBox()
		self.info = gtk.Label("")
		self.show_click_settings()
		gobject.timeout_add(1000, self.show_click_settings)
		vbox.pack_start(self.info, False, False, 0)
		self.label = gtk.Label("Ready")
		vbox.pack_start(self.label, False, False, 0)

		self.eventbox = gtk.EventBox()
		self.eventbox.connect('button-press-event', self.button_press_event)
		self.eventbox.add_events(gtk.gdk.BUTTON_PRESS_MASK)
		self.eventbox.add_events(gtk.gdk.BUTTON_RELEASE_MASK)
		vbox.pack_start(self.eventbox, True, True, 0)

		self.window.add(vbox)
		self.window.show_all()

	def show_click_settings(self):
		root = gtk.gdk.get_default_root_window()
		screen = root.get_screen()
		#use undocumented constants found in source:
		try:
			t = screen.get_setting("gtk-double-click-time")
		except:
			t = ""
		try:
			d = screen.get_setting("gtk-double-click-distance")
		except:
			d = ""
		self.info.set_text("Time (ms): %s, Distance: %s" % (t, d))
		return True

	def button_press_event(self, obj, event):
		if event.type == gtk.gdk._3BUTTON_PRESS:
			self.label.set_text("Triple Click!")
		elif event.type == gtk.gdk._2BUTTON_PRESS:
			self.label.set_text("Double Click!")
		elif event.type == gtk.gdk.BUTTON_PRESS:
			self.label.set_text("Click")
		else:
			self.label.set_text("Unexpected event: %s" % event)

def main():
	TestForm()
	gtk.main()


if __name__ == "__main__":
	main()
	sys.exit(0)
