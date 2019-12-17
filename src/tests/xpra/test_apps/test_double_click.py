#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013-2019 Antoine Martin <antoine@xpra.org>

import sys
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib  #pylint: disable=wrong-import-position


class TestForm(object):

	def	__init__(self):
		self.window = Gtk.Window(Gtk.WindowType.TOPLEVEL)
		self.window.connect("destroy", Gtk.main_quit)
		self.window.set_default_size(320, 200)
		self.window.set_border_width(20)

		vbox = Gtk.VBox()
		self.info = Gtk.Label("")
		self.show_click_settings()
		GLib.timeout_add(1000, self.show_click_settings)
		vbox.pack_start(self.info, False, False, 0)
		self.label = Gtk.Label("Ready")
		vbox.pack_start(self.label, False, False, 0)

		self.eventbox = Gtk.EventBox()
		self.eventbox.connect('button-press-event', self.button_press_event)
		self.eventbox.add_events(Gdk.EventMask.BUTTON_PRESS)
		self.eventbox.add_events(Gdk.EventMask.BUTTON_RELEASE)
		vbox.pack_start(self.eventbox, True, True, 0)

		self.window.add(vbox)
		self.window.show_all()

	def show_click_settings(self):
		root = Gdk.get_default_root_window()
		screen = root.get_screen()
		#use undocumented constants found in source:
		try:
			t = screen.get_setting("gtk-double-click-time")
		except Exception:
			t = ""
		try:
			d = screen.get_setting("gtk-double-click-distance")
		except Exception:
			d = ""
		self.info.set_text("Time (ms): %s, Distance: %s" % (t, d))
		return True

	def button_press_event(self, obj, event):
		if event.type == Gdk._3BUTTON_PRESS:
			self.label.set_text("Triple Click!")
		elif event.type == Gdk._2BUTTON_PRESS:
			self.label.set_text("Double Click!")
		elif event.type == Gdk.BUTTON_PRESS:
			self.label.set_text("Click")
		else:
			self.label.set_text("Unexpected event: %s" % event)

def main():
	TestForm()
	Gtk.main()


if __name__ == "__main__":
	main()
	sys.exit(0)
