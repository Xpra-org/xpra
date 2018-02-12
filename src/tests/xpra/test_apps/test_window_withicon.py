#!/usr/bin/env python

import os

from xpra.gtk_common.gobject_compat import import_gtk
from xpra.gtk_common.gtk_util import WINDOW_TOPLEVEL

gtk = import_gtk()


def main():
	window = gtk.Window(WINDOW_TOPLEVEL)
	window.set_size_request(400, 200)
	window.connect("delete_event", gtk.main_quit)
	for x in ("/usr/share/icons/gnome/48x48/emblems/emblem-important.png", "/opt/share/icons/xpra.png"):
		if os.path.exists(x):
			print("using %s" % x)
			window.set_icon_from_file(x)
			break
	window.show_all()
	gtk.main()
	return 0


if __name__ == "__main__":
	main()
