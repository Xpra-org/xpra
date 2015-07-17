#!/usr/bin/env python

import gtk

width = 400
height = 200
def main():
	window = gtk.Window(gtk.WINDOW_TOPLEVEL)
	#window = gtk.Window(gtk.WINDOW_POPUP)
	window.set_size_request(width, height)
	window.connect("delete_event", gtk.mainquit)

	close_btn = gtk.Button("Close via X11 Message")
	def close(*args):
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
		now = gtk.gdk.x11_get_server_time(window.get_window())
		X11Window.sendClientMessage(root_xid, xwin, False, event_mask, "_NET_CLOSE_WINDOW", now, 1)
	close_btn.connect('clicked', close)

	window.add(close_btn)
	window.show_all()
	gtk.main()
	return 0


if __name__ == "__main__":
	main()
