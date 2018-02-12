#!/usr/bin/env python

from xpra.gtk_common.gobject_compat import import_gtk
from xpra.gtk_common.gtk_util import WINDOW_TOPLEVEL, get_root_size

gtk = import_gtk()

def change_callback(self, window, entry):
	print("text=%s" % entry.get_text())
	window.set_title(entry.get_text())

width = 400
height = 200
def main():
	window = gtk.Window(WINDOW_TOPLEVEL)
	window.set_size_request(width, height)
	window.connect("delete_event", gtk.main_quit)
	vbox = gtk.VBox(False, 0)
	hbox = gtk.HBox(False, 0)
	vbox.pack_start(hbox, expand=False, fill=False, padding=10)
	btn = gtk.Button("move me")
	hbox.pack_start(btn, expand=False, fill=False, padding=10)
	def move(*_args):
		x, y = window.get_position()
		maxx, maxy = get_root_size()
		new_x = (x+100) % maxx
		new_y = (y+100) % maxy
		print("moving to %s x %s" % (new_x, new_y))
		window.move(new_x, new_y)
	btn.connect('clicked', move)
	window.add(vbox)
	window.show_all()
	gtk.main()
	return 0


if __name__ == "__main__":
	main()
