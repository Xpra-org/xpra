#!/usr/bin/env python

from gi.repository import Gtk

from xpra.gtk_common.gtk_util import WINDOW_TOPLEVEL


def main():
	window = Gtk.Window(WINDOW_TOPLEVEL)
	window.set_size_request(320, 500)
	window.connect("delete_event", Gtk.main_quit)
	vbox = Gtk.VBox(False, 0)

	b = Gtk.Button("Modal Window")
	def show_modal_window(*args):
		modal = Gtk.Window(WINDOW_TOPLEVEL)
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
