#!/usr/bin/env python

from xpra.gtk_common.gobject_compat import import_gtk
from xpra.gtk_common.gtk_util import WINDOW_TOPLEVEL

gtk = import_gtk()


def main():
	window = gtk.Window(WINDOW_TOPLEVEL)
	window.set_size_request(400, 100)
	window.connect("delete_event", gtk.main_quit)
	entry = gtk.Entry()
	entry.set_max_length(50)
	title = "Hello"
	import sys
	if len(sys.argv)>1:
		title = sys.argv[1]
	entry.set_text("right click here to get a popup")
	entry.show()
	window.set_title(title)
	window.add(entry)
	window.show_all()
	gtk.main()
	return 0

if __name__ == "__main__":
	main()
