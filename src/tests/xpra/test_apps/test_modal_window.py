#!/usr/bin/env python

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk	#pylint: disable=wrong-import-position


def main():
	window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
	window.set_size_request(320, 500)
	window.connect("delete_event", Gtk.main_quit)
	vbox = Gtk.VBox(False, 0)

	b = Gtk.Button("Modal Window")
	def show_modal_window(*_args):
		modal = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
		modal.set_transient_for(window)
		modal.set_modal(True)
		modal.show()
	b.connect('clicked', show_modal_window)
	vbox.add(b)
	window.add(vbox)
	window.show_all()
	Gtk.main()
	return 0


if __name__ == "__main__":
	main()
