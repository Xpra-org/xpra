#!/usr/bin/env python

from gi.repository import Gtk
from xpra.gtk_common.gtk_util import choose_file

def main():
	file_filter = Gtk.FileFilter()
	file_filter.set_name("Xpra")
	file_filter.add_pattern("*.xpra")
	window = None
	choose_file(window, "test", Gtk.FileChooserAction.OPEN, Gtk.STOCK_OPEN, None)
	return 0


if __name__ == "__main__":
	main()
