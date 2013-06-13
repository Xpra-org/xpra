#!/usr/bin/env python

import gtk

def main():
	window = gtk.Window(gtk.WINDOW_TOPLEVEL)
	window.set_size_request(400, 200)
	window.connect("delete_event", gtk.mainquit)
	vbox = gtk.VBox(False, 0)
	hbox = gtk.HBox(False, 0)
	vbox.pack_start(hbox, expand=False, fill=False, padding=10)

	maximize_btn = gtk.Button("maximize me")
	def maximize(*args):
		window.maximize()
	maximize_btn.connect('clicked', maximize)
	hbox.pack_start(maximize_btn, expand=False, fill=False, padding=10)

	unmaximize_btn = gtk.Button("unmaximize me")
	def unmaximize(*args):
		window.unmaximize()
	maximize_btn.connect('clicked', unmaximize)
	hbox.pack_start(unmaximize_btn, expand=False, fill=False, padding=10)

	fullscreen_btn = gtk.Button("fullscreen me")
	def fullscreen(*args):
		window.fullscreen()
	fullscreen_btn.connect('clicked', fullscreen)
	hbox.pack_start(fullscreen_btn, expand=False, fill=False, padding=10)
	window.add(vbox)
	window.show_all()
	gtk.main()
	return 0


if __name__ == "__main__":
	main()
