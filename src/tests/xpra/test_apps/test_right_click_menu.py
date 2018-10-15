#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>

import sys
import pygtk
pygtk.require('2.0')
import gtk


class TestForm(object):

	def	__init__(self):
		self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
		self.window.connect("destroy", gtk.main_quit)
		self.window.set_default_size(320, 200)
		self.window.set_border_width(20)
		self.window.add_events(gtk.gdk.BUTTON_PRESS_MASK)

		btn = gtk.Button("hello")
		btn.connect("button_press_event", self.button_clicked)

		self.window.add(btn)
		self.window.show_all()

	def button_clicked(self, widget, event):
		print("button_clicked("+str(widget)+", "+str(event)+")")
		menu = gtk.Menu()
		menu.append(gtk.MenuItem("Foo"))
		menu.append(gtk.MenuItem("Bar"))
		menu.show_all()
		menu.popup(None, None, None, event.button, event.time)


def main():
	TestForm()
	gtk.main()


if __name__ == "__main__":
	main()
	sys.exit(0)
