#!/usr/bin/env python

import gtk

_NET_WM_MOVERESIZE_SIZE_TOPLEFT      = 0
_NET_WM_MOVERESIZE_SIZE_TOP          = 1
_NET_WM_MOVERESIZE_SIZE_TOPRIGHT     = 2
_NET_WM_MOVERESIZE_SIZE_RIGHT        = 3
_NET_WM_MOVERESIZE_SIZE_BOTTOMRIGHT  = 4
_NET_WM_MOVERESIZE_SIZE_BOTTOM       = 5
_NET_WM_MOVERESIZE_SIZE_BOTTOMLEFT   = 6
_NET_WM_MOVERESIZE_SIZE_LEFT         = 7
_NET_WM_MOVERESIZE_MOVE              = 8
_NET_WM_MOVERESIZE_SIZE_KEYBOARD     = 9
_NET_WM_MOVERESIZE_MOVE_KEYBOARD     = 10
_NET_WM_MOVERESIZE_CANCEL            = 11

width = 400
height = 200
def main():
	window = gtk.Window(gtk.WINDOW_TOPLEVEL)
	#window = gtk.Window(gtk.WINDOW_POPUP)
	window.set_size_request(width, height)
	window.connect("delete_event", gtk.mainquit)
	window.realize()
	root = window.get_window().get_screen().get_root_window()

	def initiate(x_root, y_root, direction, button, source_indication):
		print("initiate%s" % str((x_root, y_root, direction, button, source_indication)))
		from xpra.x11.gtk_x11 import gdk_display_source
		assert gdk_display_source
		from xpra.x11.bindings.core_bindings import X11CoreBindings					#@UnresolvedImport
		from xpra.x11.bindings.window_bindings import constants, X11WindowBindings  #@UnresolvedImport
		event_mask = constants["SubstructureNotifyMask"] | constants["SubstructureRedirectMask"]
		from xpra.gtk_common.gobject_compat import get_xid
		root_xid = get_xid(root)
		xwin = get_xid(window.get_window())
		X11Core = X11CoreBindings()
		X11Core.UngrabPointer()
		X11Window = X11WindowBindings()
		X11Window.sendClientMessage(root_xid, xwin, False, event_mask, "_NET_WM_MOVERESIZE",
			  x_root, y_root, direction, button, source_indication)

	def cancel():
		initiate(0, 0, _NET_WM_MOVERESIZE_CANCEL, 0, 1)

	vbox = gtk.VBox(False, 0)
	btn = gtk.Button("initiate move")
	vbox.pack_start(btn, expand=False, fill=False, padding=10)
	def initiate_move(*args):
		cancel()
		x, y = root.get_pointer()[:2]
		source_indication = 1	#normal
		button = 1
		direction = _NET_WM_MOVERESIZE_MOVE
		initiate(x, y, direction, button, source_indication)
	btn.connect('button-press-event', initiate_move)

	btn = gtk.Button("initiate move resize")
	vbox.pack_start(btn, expand=False, fill=False, padding=10)
	def initiate_resize(*args):
		cancel()
		x, y = root.get_pointer()[:2]
		source_indication = 1	#normal
		button = 1
		direction = _NET_WM_MOVERESIZE_SIZE_BOTTOMRIGHT
		initiate(x, y, direction, button, source_indication)
	btn.connect('clicked', initiate_resize)

	window.add(vbox)
	window.show_all()
	gtk.main()
	return 0


if __name__ == "__main__":
	main()
