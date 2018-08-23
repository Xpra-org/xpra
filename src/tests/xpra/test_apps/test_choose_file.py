#!/usr/bin/env python

from xpra.gtk_common.gobject_compat import import_gtk
gtk = import_gtk()
from xpra.gtk_common.gtk_util import choose_file, FILE_CHOOSER_ACTION_OPEN

def main():
	file_filter = gtk.FileFilter()
	file_filter.set_name("Xpra")
	file_filter.add_pattern("*.xpra")
	window = None
	choose_file(window, "test", FILE_CHOOSER_ACTION_OPEN, gtk.STOCK_OPEN, None)
	return 0


if __name__ == "__main__":
	main()
