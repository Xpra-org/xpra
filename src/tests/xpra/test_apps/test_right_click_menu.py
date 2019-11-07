#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk


class TestForm(object):

	def	__init__(self):
		self.window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
		self.window.connect("destroy", Gtk.main_quit)
		self.window.set_default_size(320, 200)
		self.window.set_border_width(20)
		self.window.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)

		btn = Gtk.Button("hello")
		btn.connect("button_press_event", self.button_clicked)

		self.window.add(btn)
		self.window.show_all()

	def button_clicked(self, widget, event):
		print("button_clicked("+str(widget)+", "+str(event)+")")
		menu = Gtk.Menu()
		menu.append(Gtk.MenuItem("Foo"))
		menu.append(Gtk.MenuItem("Bar"))
		menu.show_all()
		menu.popup(None, None, None, event.button, event.time)


def main():
	TestForm()
	gtk.main()


if __name__ == "__main__":
	main()
	sys.exit(0)
