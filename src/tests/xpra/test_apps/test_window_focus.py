#!/usr/bin/env python

import os

from xpra.gtk_common.gobject_compat import import_gtk
from xpra.gtk_common.error import xlog
from xpra.gtk_common.gtk_util import WINDOW_TOPLEVEL, get_xwindow
from xpra.x11.gtk_x11.gdk_display_source import init_gdk_display_source
from xpra.x11.gtk_x11.gdk_bindings import init_x11_filter
from xpra.x11.bindings.window_bindings import X11WindowBindings  #pylint: disable=no-name-in-module

gtk = import_gtk()


def main():
	window = gtk.Window(WINDOW_TOPLEVEL)
	window.set_size_request(400, 100)
	window.connect("delete_event", gtk.main_quit)
	da = gtk.DrawingArea()
	window.add(da)
	window.show_all()
	#self.selectX11FocusChange(self)
	def focus_in(_window, event):
		print("focus-in-event")
	def focus_out(_window, event):
		print("focus-out-event")
	def has_toplevel_focus(_window, event):
		print("has-toplevel-event")
	window.connect("focus-in-event", focus_in)
	window.connect("focus-out-event", focus_out)
	window.connect("notify::has-toplevel-focus", has_toplevel_focus)
	#x11 focus events:
	gdk_win = window.get_window()
	xid = get_xwindow(gdk_win)
	init_gdk_display_source()
	os.environ["XPRA_X11_DEBUG_EVENTS"] = "FocusIn,FocusOut"
	init_x11_filter()
	with xlog:
		X11WindowBindings().selectFocusChange(xid)

	gtk.main()
	return 0

if __name__ == "__main__":
	main()
