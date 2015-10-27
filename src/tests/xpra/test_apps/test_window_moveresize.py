#!/usr/bin/env python

import gtk
import gobject

width = 400
height = 200
class MoveWindow(gtk.Window):
	def __init__(self, window_type):
		gtk.Window.__init__(self, window_type)
		self.set_size_request(width, height)
		self.connect("delete_event", gtk.mainquit)
		vbox = gtk.VBox(False, 0)
		hbox = gtk.HBox(False, 0)
		vbox.pack_start(hbox, expand=False, fill=False, padding=10)

		gtk_btn = gtk.Button("move+resize via GTK")
		hbox.pack_start(gtk_btn, expand=False, fill=False, padding=10)
		gtk_btn.connect('clicked', self.moveresize_GTK)

		x11_btn = gtk.Button("move+resize via x11")
		hbox.pack_start(x11_btn, expand=False, fill=False, padding=10)
		x11_btn.connect('clicked', self.moveresize_X11)

		self.add(vbox)
		self.show_all()
		gobject.timeout_add(5*1000, self.moveresize_GTK)
		gobject.timeout_add(10*1000, self.moveresize_X11)

	def moveresize_GTK(self, *args):
		new_x, new_y, new_width, new_height = self.get_new_geometry()
		self.move(new_x, new_y)
		self.resize(new_width, new_height)

	def moveresize_X11(self, *args):
		new_x, new_y, new_width, new_height = self.get_new_geometry()
		from xpra.x11.gtk2 import gdk_display_source
		assert gdk_display_source
		from xpra.gtk_common.gobject_compat import get_xid
		from xpra.x11.bindings.window_bindings import constants, X11WindowBindings  #@UnresolvedImport
		X11Window = X11WindowBindings()
		root = self.get_window().get_screen().get_root_window()
		root_xid = get_xid(root)
		xwin = get_xid(self.get_window())
		SubstructureNotifyMask = constants["SubstructureNotifyMask"]
		SubstructureRedirectMask = constants["SubstructureRedirectMask"]
		event_mask = SubstructureNotifyMask | SubstructureRedirectMask
		X11Window.sendClientMessage(root_xid, xwin, False, event_mask, "_NET_MOVERESIZE_WINDOW",
			  1+2**8+2**9+2**10+2**11, new_x, new_y, new_width, new_height)

	def get_new_geometry(self):
		x, y = self.get_position()
		width, height = self.get_size()
		maxx, maxy = gtk.gdk.get_default_root_window().get_geometry()[2:4]
		new_x = (x+100) % (maxx-width)
		new_y = (y+100) % (maxy-height)
		width, height = self.get_size()
		return new_x, new_y, (width + 100) % (maxx-x), (height + 100) % (maxy-y)


def main():
	MoveWindow(gtk.WINDOW_TOPLEVEL)
	MoveWindow(gtk.WINDOW_POPUP)
	gtk.main()


if __name__ == "__main__":
	main()
