#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>

import sys
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk  #pylint: disable=wrong-import-position


class TestForm(object):

	def	__init__(self):
		self.window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
		self.window.connect("destroy", Gtk.main_quit)
		self.window.set_default_size(320, 200)
		self.window.set_border_width(20)

		box = Gtk.VBox()
		box.add(Gtk.Entry())
		cb = Gtk.combo_box_new_text()
		cb.append_text("foo")
		cb.append_text("bar")
		box.add(cb)

		self.window.add(box)
		self.window.show_all()


def main():
	TestForm()
	Gtk.main()


if __name__ == "__main__":
	main()
	sys.exit(0)
