#!/usr/bin/env python
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform import program_context
from xpra.platform.gui import force_focus
from xpra.gtk_common.gtk_util import add_close_accel

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib  #pylint: disable=wrong-import-position


width = 400
height = 200

def make_win():
	window = Gtk.Window(type=Gtk.WindowType.POPUP)
	window.set_title("Main")
	window.set_size_request(width, height)
	window.connect("delete_event", Gtk.main_quit)
	window.set_events(Gdk.EventMask.KEY_PRESS_MASK | Gdk.EventMask.BUTTON_PRESS_MASK)
	def on_press(*_args):
		Gtk.main_quit()
	window.connect("key_press_event", on_press)
	window.connect("button_press_event", on_press)
	return window

def main():
	with program_context("window-overrideredirect", "Window Override Redirect"):
		w = make_win()
		def show_with_focus():
			force_focus()
			w.show_all()
			w.present()
		add_close_accel(w, Gtk.main_quit)
		GLib.idle_add(show_with_focus)
		Gtk.main()


if __name__ == "__main__":
	main()
