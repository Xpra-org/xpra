#!/usr/bin/env python

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk	#pylint: disable=wrong-import-position


width = 400
height = 200
def main():
	window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
	#window = gtk.Window(gtk.WINDOW_POPUP)
	window.set_size_request(width, height)
	window.connect("delete_event", Gtk.main_quit)
	vbox = Gtk.VBox()

	def send_net_showing_desktop(v):
		from xpra.x11.gtk_x11.gdk_display_source import init_gdk_display_source
		from xpra.x11.bindings.window_bindings import constants, X11WindowBindings  #@UnresolvedImport
		init_gdk_display_source()
		X11Window = X11WindowBindings()
		root = window.get_window().get_screen().get_root_window()
		root_xid = root.get_xid()
		SubstructureNotifyMask = constants["SubstructureNotifyMask"]
		SubstructureRedirectMask = constants["SubstructureRedirectMask"]
		event_mask = SubstructureNotifyMask | SubstructureRedirectMask
		X11Window.sendClientMessage(root_xid, root_xid, False, event_mask, "_NET_SHOWING_DESKTOP", v)

	b = Gtk.Button(label="Show Desktop")
	def show_desktop(*_args):
		send_net_showing_desktop(1)
	b.connect('clicked', show_desktop)
	vbox.add(b)

	b = Gtk.Button(label="Not Show Desktop")
	def not_show_desktop(*_args):
		send_net_showing_desktop(0)
	b.connect('clicked', not_show_desktop)
	vbox.add(b)

	window.add(vbox)
	window.show_all()
	Gtk.main()
	return 0


if __name__ == "__main__":
	main()
