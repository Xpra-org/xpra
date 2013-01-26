#!/usr/bin/env python
# This file is part of Parti.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>

import time
import pygtk
pygtk.require('2.0')
import gtk.gdk

from wimpiggy.lowlevel import get_keycodes_down		#@UnresolvedImport

def main():
	while True:
		down = get_keycodes_down(gtk.gdk.get_default_root_window())
		print("down=%s" % down)
		time.sleep(1)


if __name__ == "__main__":
	main()
