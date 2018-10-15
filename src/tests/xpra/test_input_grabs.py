#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>

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
		combo = gtk.combo_box_new_text()
		combo.append_text("hello 1")
		combo.append_text("hello 2")
		vbox.add(combo)

		button = gtk.Button("grab in 5 seconds")
		button.connect("clicked", self.delayed_grab)
		vbox.add(button)

		self.window.add(vbox)
		self.window.show_all()

	def delayed_grab(self, *args):
		def grab():
			r = gtk.gdk.pointer_grab(self.window.get_window(), owner_events=False,
									event_mask=gtk.gdk.BUTTON_PRESS_MASK | gtk.gdk.BUTTON_RELEASE_MASK,
									confine_to=None, cursor=None, time=0L)
			print("pointer_grab(..)=%s" % {
										gtk.gdk.GRAB_SUCCESS : "SUCCESS",
										gtk.gdk.GRAB_ALREADY_GRABBED : "ALREADY_GRABBED",
										gtk.gdk.GRAB_INVALID_TIME : "INVALID_TIME",
										gtk.gdk.GRAB_NOT_VIEWABLE : "NOT_VIEWABLE",
										gtk.gdk.GRAB_FROZEN	: "FROZEN"}.get(r))
			if r==gtk.gdk.GRAB_SUCCESS:
				def ungrab():
					print("pointer_ungrab()")
					gtk.gdk.pointer_ungrab(0L)
				gobject.timeout_add(5000, ungrab)
		gobject.timeout_add(5000, grab)


def main():
	TestForm()
	gtk.main()


if __name__ == "__main__":
	main()
	sys.exit(0)
