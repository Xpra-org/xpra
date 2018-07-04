#!/usr/bin/env python

from xpra.gtk_common.gobject_compat import import_gtk, import_gdk
from xpra.gtk_common.gtk_util import WINDOW_TOPLEVEL

gtk = import_gtk()
gdk = import_gdk()


def main():
	window = gtk.Window(WINDOW_TOPLEVEL)
	window.set_size_request(320, 500)
	window.connect("delete_event", gtk.main_quit)
	vbox = gtk.VBox(False, 0)

	b = gtk.Button("Modal Window")
	def show_modal_window(*args):
		modal = gtk.Window(WINDOW_TOPLEVEL)
		modal.set_transient_for(window)
		modal.set_modal(True)
		modal.show()
	b.connect('clicked', show_modal_window)
	vbox.add(b)
	window.add(vbox)
	window.show_all()
	gtk.main()
	return 0


if __name__ == "__main__":
	main()
