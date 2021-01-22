#!/usr/bin/env python

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk  #pylint: disable=wrong-import-position


def main():
	display = Gdk.Display.get_default()
	#cursor from name:
	cursor = Gdk.Cursor.new_from_name(display, "xterm")
	cursors = [("new_from_name", cursor)]
	surface, xhot, yhot = cursor.get_surface()
	#from the pixbuf:
	pixbuf = cursor.get_image()
	import binascii
	print("pixbuf non-zero pixels=%s" % binascii.hexlify(pixbuf.get_pixels()).rstrip(b"0"))
	pcursor = Gdk.Cursor.new_from_pixbuf(display, pixbuf, xhot, yhot)
	cursors.append(("new_from_pixbuf", pcursor))
	w = surface.get_width()
	h = surface.get_height()
	pixbuf = Gdk.pixbuf_get_from_surface(surface, 0, 0, w, h)
	pscursor = Gdk.Cursor.new_from_pixbuf(display, pixbuf, xhot, yhot)
	cursors.append(("new_from_pixbuf from surface", pscursor))
	scursor = Gdk.Cursor.new_from_surface(display, surface, xhot, yhot)
	cursors.append(("new_from_surface", scursor))

	w = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
	w.connect("delete_event", Gtk.main_quit)
	w.set_title("Cursor Pixbuf Test")
	w.set_size_request(320, 200)
	b = Gtk.Button()
	def change_cursor(*_args):
		info, cursor = cursors.pop(0)
		print("%s : %s" % (info, cursor))
		w.get_window().set_cursor(cursor)
		cursors.append((info, cursor))
	b.connect("clicked", change_cursor)
	w.add(b)
	w.show_all()
	change_cursor()
	Gtk.main()
	return 0


if __name__ == "__main__":
	main()
