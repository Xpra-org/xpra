#!/usr/bin/env python

import gtk
import gobject

width = 400
height = 200
def main():
	window = gtk.Window(gtk.WINDOW_TOPLEVEL)
	window.set_size_request(width, height)
	window.connect("delete_event", gtk.mainquit)
	vbox = gtk.VBox(False, 0)
	hbox = gtk.HBox(False, 0)
	vbox.pack_start(hbox, expand=False, fill=False, padding=10)
	btn = gtk.Button("raise me in 5 seconds")
	hbox.pack_start(btn, expand=False, fill=False, padding=10)
	def move_clicked(*args):
		gobject.timeout_add(5*1000, window.present)
	btn.connect('clicked', move_clicked)
	window.add(vbox)
	window.show_all()
	gtk.main()
	return 0


if __name__ == "__main__":
	main()
