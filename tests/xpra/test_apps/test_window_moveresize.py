#!/usr/bin/env python

import gi
gi.require_version("Gtk", "3.0")
gi.require_version('GdkX11', '3.0')
from gi.repository import Gtk, GdkX11, GLib   #pylint: disable=wrong-import-position

width = 400
height = 200
class MoveWindow(Gtk.Window):
	def __init__(self, window_type):
		super().__init__(type=window_type)
		self.set_size_request(width, height)
		self.connect("delete_event", Gtk.main_quit)
		vbox = Gtk.VBox(False, 0)
		hbox = Gtk.HBox(False, 0)
		vbox.pack_start(hbox, expand=False, fill=False, padding=10)

		gtk_btn = Gtk.Button(label="move+resize via GTK")
		hbox.pack_start(gtk_btn, expand=False, fill=False, padding=10)
		gtk_btn.connect('clicked', self.moveresize_GTK)

		x11_btn = Gtk.Button(label="move+resize via x11")
		hbox.pack_start(x11_btn, expand=False, fill=False, padding=10)
		x11_btn.connect('clicked', self.moveresize_X11)

		self.add(vbox)
		self.show_all()
		GLib.timeout_add(5*1000, self.moveresize_GTK)
		GLib.timeout_add(10*1000, self.moveresize_X11)

	def moveresize_GTK(self, *_args):
		new_x, new_y, new_width, new_height = self.get_new_geometry()
		self.move(new_x, new_y)
		self.resize(new_width, new_height)

	def moveresize_X11(self, *_args):
		new_x, new_y, new_width, new_height = self.get_new_geometry()
		from xpra.x11.gtk_x11.gdk_display_source import init_gdk_display_source
		init_gdk_display_source()
		from xpra.x11.bindings.window_bindings import constants, X11WindowBindings  #@UnresolvedImport
		X11Window = X11WindowBindings()
		root = self.get_window().get_screen().get_root_window()
		root_xid = root.xid
		xwin = self.get_window().xid
		SubstructureNotifyMask = constants["SubstructureNotifyMask"]
		SubstructureRedirectMask = constants["SubstructureRedirectMask"]
		event_mask = SubstructureNotifyMask | SubstructureRedirectMask
		X11Window.sendClientMessage(root_xid, xwin, False, event_mask, "_NET_MOVERESIZE_WINDOW",
			  1+2**8+2**9+2**10+2**11, new_x, new_y, new_width, new_height)

	def get_new_geometry(self):
		x, y = self.get_position()
		width, height = self.get_size()
		from xpra.gtk_common.gtk_util import get_default_root_window
		maxx, maxy = get_default_root_window().get_geometry()[2:4]
		new_x = (x+100) % (maxx-width)
		new_y = (y+100) % (maxy-height)
		width, height = self.get_size()
		return new_x, new_y, (width + 100) % (maxx-x), (height + 100) % (maxy-y)


def main():
	MoveWindow(Gtk.WindowType.TOPLEVEL)
	MoveWindow(Gtk.WindowType.POPUP)
	Gtk.main()


if __name__ == "__main__":
	main()
