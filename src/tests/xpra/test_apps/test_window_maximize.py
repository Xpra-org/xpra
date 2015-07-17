#!/usr/bin/env python

import gtk.gdk

def main():
	window = gtk.Window(gtk.WINDOW_TOPLEVEL)
	window.set_size_request(220, 120)
	window.connect("delete_event", gtk.mainquit)
	vbox = gtk.VBox(False, 0)

	def add_buttons(t1, cb1, t2, cb2):
		hbox = gtk.HBox(True, 10)
		b1 = gtk.Button(t1)
		def vcb1(*args):
			cb1()
		b1.connect('clicked', vcb1)
		hbox.pack_start(b1, expand=True, fill=False, padding=5)
		b2 = gtk.Button(t2)
		def vcb2(*args):
			cb2()
		b2.connect('clicked', vcb2)
		hbox.pack_start(b2, expand=True, fill=False, padding=5)
		vbox.pack_start(hbox, expand=False, fill=False, padding=2)

	def send_maximized_wm_state(mode):
		from xpra.x11.gtk2 import gdk_display_source
		assert gdk_display_source
		from xpra.gtk_common.gobject_compat import get_xid
		from xpra.x11.bindings.window_bindings import constants, X11WindowBindings  #@UnresolvedImport
		X11Window = X11WindowBindings()
		root = window.get_window().get_screen().get_root_window()
		root_xid = get_xid(root)
		xwin = get_xid(window.get_window())
		SubstructureNotifyMask = constants["SubstructureNotifyMask"]
		SubstructureRedirectMask = constants["SubstructureRedirectMask"]
		event_mask = SubstructureNotifyMask | SubstructureRedirectMask
		X11Window.sendClientMessage(root_xid, xwin, False, event_mask, "_NET_WM_STATE", mode,
			  "_NET_WM_STATE_MAXIMIZED_VERT", "_NET_WM_STATE_MAXIMIZED_HORZ", 0, 0)

	def maximize_X11(*args):
		send_maximized_wm_state(1)	#ADD
	def unmaximize_X11(*args):
		send_maximized_wm_state(2)	#REMOVE

	add_buttons("maximize", window.maximize, "unmaximize", window.unmaximize)
	add_buttons("maximize X11", maximize_X11, "unmaximize X11", unmaximize_X11)
	add_buttons("fullscreen", window.fullscreen, "unfullscreen", window.unfullscreen)

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
