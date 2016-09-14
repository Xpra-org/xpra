#!/usr/bin/env python

import gtk

from xpra.util import MOVERESIZE_DIRECTION_STRING, MOVERESIZE_SIZE_TOPLEFT, MOVERESIZE_SIZE_TOP, \
                        MOVERESIZE_SIZE_TOPRIGHT, MOVERESIZE_SIZE_RIGHT, MOVERESIZE_SIZE_BOTTOMRIGHT, \
                        MOVERESIZE_SIZE_BOTTOM, MOVERESIZE_SIZE_BOTTOMLEFT, MOVERESIZE_SIZE_LEFT, \
                        MOVERESIZE_MOVE, MOVERESIZE_CANCEL

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
		from xpra.x11.gtk2 import gdk_display_source
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
		initiate(0, 0, MOVERESIZE_CANCEL, 0, 1)


	table = gtk.Table(3, 3, True)
	table.set_col_spacings(0)
	table.set_row_spacings(0)

	btn = gtk.Button("initiate move")
	table.attach(btn, 1, 2, 1, 2, xoptions=gtk.FILL, yoptions=gtk.FILL)
	def initiate_move(*args):
		cancel()
		x, y = root.get_pointer()[:2]
		source_indication = 1	#normal
		button = 1
		direction = MOVERESIZE_MOVE
		initiate(x, y, direction, button, source_indication)
	btn.connect('button-press-event', initiate_move)

	def btn_callback(btn, event, direction):
		cancel()
		x, y = root.get_pointer()[:2]
		source_indication = 1	#normal
		button = 1
		initiate(x, y, direction, button, source_indication)
	def add_button(x, y, direction):
		btn = gtk.Button(MOVERESIZE_DIRECTION_STRING[direction])
		table.attach(btn, x, x+1, y, y+1, xoptions=gtk.EXPAND|gtk.FILL, yoptions=gtk.EXPAND|gtk.FILL)
		btn.connect('button-press-event', btn_callback, direction)

	for x,y,direction in (
						(0, 0, MOVERESIZE_SIZE_TOPLEFT),
						(1, 0, MOVERESIZE_SIZE_TOP),
						(2, 0, MOVERESIZE_SIZE_TOPRIGHT),
						(0, 1, MOVERESIZE_SIZE_LEFT),
						(1, 1, MOVERESIZE_MOVE),
						(2, 1, MOVERESIZE_SIZE_RIGHT),
						(0, 2, MOVERESIZE_SIZE_BOTTOMLEFT),
						(1, 2, MOVERESIZE_SIZE_BOTTOM),
						(2, 2, MOVERESIZE_SIZE_BOTTOMRIGHT),
							):
		add_button(x, y, direction)

	window.add(table)
	window.show_all()
	gtk.main()
	return 0


if __name__ == "__main__":
	main()
