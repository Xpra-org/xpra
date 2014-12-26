#!/usr/bin/env python

import gtk.gdk

def main():
	window = gtk.Window(gtk.WINDOW_TOPLEVEL)
	window.set_size_request(200, 300)
	window.connect("delete_event", gtk.mainquit)
	vbox = gtk.VBox(False, 0)

	maximize_btn = gtk.Button("maximize me")
	def maximize(*args):
		window.maximize()
	maximize_btn.connect('clicked', maximize)
	vbox.pack_start(maximize_btn, expand=False, fill=False, padding=10)

	unmaximize_btn = gtk.Button("unmaximize me")
	def unmaximize(*args):
		window.unmaximize()
	unmaximize_btn.connect('clicked', unmaximize)
	vbox.pack_start(unmaximize_btn, expand=False, fill=False, padding=10)

	fullscreen_btn = gtk.Button("fullscreen me")
	def fullscreen(*args):
		window.fullscreen()
	fullscreen_btn.connect('clicked', fullscreen)
	vbox.pack_start(fullscreen_btn, expand=False, fill=False, padding=10)

	unfullscreen_btn = gtk.Button("unfullscreen me")
	def unfullscreen(*args):
		window.unfullscreen()
	unfullscreen_btn.connect('clicked', unfullscreen)
	vbox.pack_start(unfullscreen_btn, expand=False, fill=False, padding=10)

	def window_state(widget, event):
		STATES = {
				gtk.gdk.WINDOW_STATE_WITHDRAWN	: "withdrawn",
				gtk.gdk.WINDOW_STATE_ICONIFIED	: "iconified",
				gtk.gdk.WINDOW_STATE_MAXIMIZED	: "maximized",
				gtk.gdk.WINDOW_STATE_STICKY		: "sticky",
				gtk.gdk.WINDOW_STATE_FULLSCREEN	: "fullscreen",
				gtk.gdk.WINDOW_STATE_ABOVE		: "above",
				gtk.gdk.WINDOW_STATE_BELOW		: "below",
				}
		print("window_state(%s, %s)" % (widget, event))
		print("flags: %s" % [STATES[x] for x in STATES.keys() if x & event.new_window_state])
	window.connect("window-state-event", window_state)

	window.add(vbox)
	window.show_all()
	gtk.main()
	return 0


if __name__ == "__main__":
	main()
