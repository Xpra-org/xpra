#!/usr/bin/env python

import gtk

width = 400
height = 200
def main():
	window = gtk.Window(gtk.WINDOW_TOPLEVEL)
	#window = gtk.Window(gtk.WINDOW_POPUP)
	window.set_size_request(width, height)
	window.connect("delete_event", gtk.mainquit)
	vbox = gtk.VBox(False, 0)
	hbox = gtk.HBox(False, 0)
	vbox.pack_start(hbox, expand=False, fill=False, padding=10)
	def get_new_geometry():
		x, y = window.get_position()
		width, height = window.get_size()
		maxx, maxy = gtk.gdk.get_default_root_window().get_geometry()[2:4]
		new_x = (x+100) % (maxx-width)
		new_y = (y+100) % (maxy-height)
		width, height = window.get_size()
		return new_x, new_y, (width + 100) % (maxx-x), (height + 100) % (maxy-y)
	gtk_btn = gtk.Button("move+resize via GTK")
	hbox.pack_start(gtk_btn, expand=False, fill=False, padding=10)
	def moveresize_GTK(*args):
		new_x, new_y, new_width, new_height = get_new_geometry()
		window.move(new_x, new_y)
		window.resize(new_width, new_height)
	gtk_btn.connect('clicked', moveresize_GTK)

	x11_btn = gtk.Button("move+resize via x11")
	hbox.pack_start(x11_btn, expand=False, fill=False, padding=10)
	def moveresize_X11(*args):
		new_x, new_y, new_width, new_height = get_new_geometry()
		from xpra.x11.gtk_x11 import gdk_display_source
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
		X11Window.sendClientMessage(root_xid, xwin, False, event_mask, "_NET_MOVERESIZE_WINDOW",
			  1+2**8+2**9+2**10+2**11, new_x, new_y, new_width, new_height)
	x11_btn.connect('clicked', moveresize_X11)

	window.add(vbox)
	window.show_all()
	gtk.main()
	return 0


if __name__ == "__main__":
	main()
