#!/usr/bin/env python

import gtk

width = 400
height = 200
def main():
	window = gtk.Window(gtk.WINDOW_TOPLEVEL)
	#window = gtk.Window(gtk.WINDOW_POPUP)
	window.set_size_request(width, height)
	window.connect("delete_event", gtk.mainquit)
	vbox = gtk.VBox()

	def send_net_showing_desktop(v):
		from xpra.x11.gtk2 import gdk_display_source
		assert gdk_display_source
		from xpra.gtk_common.gobject_compat import get_xid
		from xpra.x11.bindings.window_bindings import constants, X11WindowBindings  #@UnresolvedImport
		X11Window = X11WindowBindings()
		root = window.get_window().get_screen().get_root_window()
		root_xid = get_xid(root)
		SubstructureNotifyMask = constants["SubstructureNotifyMask"]
		SubstructureRedirectMask = constants["SubstructureRedirectMask"]
		event_mask = SubstructureNotifyMask | SubstructureRedirectMask
		X11Window.sendClientMessage(root_xid, root_xid, False, event_mask, "_NET_SHOWING_DESKTOP", v)

	b = gtk.Button("Show Desktop")
	def show_desktop(*args):
		send_net_showing_desktop(1)
	b.connect('clicked', show_desktop)
	vbox.add(b)

	b = gtk.Button("Not Show Desktop")
	def not_show_desktop(*args):
		send_net_showing_desktop(0)
	b.connect('clicked', not_show_desktop)
	vbox.add(b)

	window.add(vbox)
	window.show_all()
	gtk.main()
	return 0


if __name__ == "__main__":
	main()
