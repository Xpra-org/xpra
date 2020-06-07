#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013-2020 Antoine Martin <antoine@xpra.org>

import sys

from xpra.platform import program_context
from xpra.platform.gui import force_focus
from xpra.gtk_common.gtk_util import add_close_accel

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib  #pylint: disable=wrong-import-position


class TestForm(object):

	def	__init__(self):
		self.window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
		self.window.connect("destroy", Gtk.main_quit)
		self.window.set_title("Test Button Events")
		self.window.set_default_size(320, 200)
		self.window.set_border_width(20)

		vbox = Gtk.VBox()
		self.info = Gtk.Label(label="")
		self.show_click_settings()
		GLib.timeout_add(1000, self.show_click_settings)
		vbox.pack_start(self.info, False, False, 0)
		self.label = Gtk.Label(label="Ready")
		vbox.pack_start(self.label, False, False, 0)

		self.eventbox = Gtk.EventBox()
		self.eventbox.connect('button-press-event', self.button_press_event)
		self.eventbox.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
		self.eventbox.add_events(Gdk.EventMask.BUTTON_RELEASE_MASK)
		vbox.pack_start(self.eventbox, True, True, 0)
		self.window.add(vbox)

	def show_with_focus(self):
		force_focus()
		self.window.show_all()
		self.window.present()

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

	def button_press_event(self, _obj, event):
		if event.type == Gdk.EventType._3BUTTON_PRESS:  #pylint: disable=protected-access
			self.label.set_text("Triple Click!")
		elif event.type == Gdk.EventType._2BUTTON_PRESS:  #pylint: disable=protected-access
			self.label.set_text("Double Click!")
		elif event.type == Gdk.EventType.BUTTON_PRESS:
			self.label.set_text("Click")
		else:
			self.label.set_text("Unexpected event: %s" % event)

def main():
	with program_context("clicks", "Clicks"):
		w = TestForm()
		add_close_accel(w.window, Gtk.main_quit)
		GLib.idle_add(w.show_with_focus)
		Gtk.main()


if __name__ == "__main__":
	main()
	sys.exit(0)
