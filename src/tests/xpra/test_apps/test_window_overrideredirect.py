#!/usr/bin/env python

from xpra.gtk_common.gobject_compat import import_gtk
from xpra.gtk_common.gtk_util import WINDOW_POPUP

gtk = import_gtk()

width = 400
height = 200

def make_win():
	window = gtk.Window(WINDOW_POPUP)
	window.set_title("Main")
	window.set_size_request(width, height)
	window.connect("delete_event", gtk.main_quit)
	window.show_all()

def main():
	make_win()
	gtk.main()


if __name__ == "__main__":
	main()
