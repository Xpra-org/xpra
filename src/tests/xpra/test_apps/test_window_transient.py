#!/usr/bin/env python

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib	#pylint: disable=wrong-import-position
from xpra.gtk_common.gtk_util import get_default_root_window


def main():
	window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
	window.set_size_request(400, 300)
	window.connect("delete_event", Gtk.main_quit)
	vbox = Gtk.VBox(False, 0)

	btn = Gtk.Button(label="Create Transient")
	def create_transient(*_args):
		tw = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
		tw.set_size_request(200, 100)
		tw.connect("delete_event", lambda x,y : tw.destroy())
		tw.set_transient_for(window)
		tw.add(Gtk.Label("Transient Window"))
		tw.show_all()
	btn.connect('clicked', create_transient)
	vbox.pack_start(btn, expand=False, fill=False, padding=10)

	btn = Gtk.Button(label="Create Transient (with 5 second delay)")
	def delayed_transient(*_args):
		GLib.timeout_add(5000, create_transient)
	btn.connect('clicked', delayed_transient)
	vbox.pack_start(btn, expand=False, fill=False, padding=10)

	btn = Gtk.Button(label="Create Root Transient")
	def create_root_transient(*_args):
		tw = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
		tw.set_size_request(200, 100)
		tw.connect("delete_event", lambda x,y : tw.destroy())
		tw.realize()
		tw.get_window().set_transient_for(get_default_root_window())
		tw.add(Gtk.Label("Transient Root Window"))
		tw.show_all()
	btn.connect('clicked', create_root_transient)
	vbox.pack_start(btn, expand=False, fill=False, padding=10)

	window.add(vbox)
	window.show_all()
	Gtk.main()
	return 0


if __name__ == "__main__":
	main()
