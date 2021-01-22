#!/usr/bin/env python

import gtk
import gobject

width = 250
height = 80
def main():
	window = gtk.Window(gtk.WINDOW_TOPLEVEL)
	window.set_size_request(width, height)
	window.connect("delete_event", gtk.mainquit)
	label = gtk.Label("hello")
	window.add(label)
	window.show_all()
	def show_time(*args):
		now = gtk.gdk.x11_get_server_time(window.get_window())
		label.set_text("x11_get_server_time=%s" % now)
		return True
	gobject.timeout_add(1000, show_time)
	gtk.main()
	return 0


if __name__ == "__main__":
	main()
