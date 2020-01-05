#!/usr/bin/env python

import os
from datetime import datetime
from collections import deque

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Pango	#pylint: disable=wrong-import-position


def main():
	window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
	window.set_size_request(640, 200)
	window.connect("delete_event", Gtk.main_quit)
	vbox = Gtk.VBox()
	N = 8
	labels = []
	font = Pango.FontDescription("sans 12")
	for _ in range(N):
		l = Gtk.Label()
		l.modify_font(font)
		labels.append(l)
	for l in labels:
		al = Gtk.Alignment(xalign=0, yalign=0.5, xscale=0.0, yscale=0)
		al.add(l)
		vbox.add(al)
	window.add(vbox)
	window.show_all()
	text = deque(maxlen=N)
	def update(s):
		text.append("%s: %s" % (datetime.now(), s))
		for i, t in enumerate(text):
			labels[i].set_text(t)
	#self.selectX11FocusChange(self)
	def focus_in(_window, event):
		update("focus-in-event")
	def focus_out(_window, event):
		update("focus-out-event")
	def has_toplevel_focus(window, _event):
		update("has-toplevel-focus: %s" % window.has_toplevel_focus())
	window.connect("focus-in-event", focus_in)
	window.connect("focus-out-event", focus_out)
	window.connect("notify::has-toplevel-focus", has_toplevel_focus)
	if os.name=="posix":
		from xpra.gtk_common.error import xlog
		from xpra.x11.gtk_x11.gdk_display_source import init_gdk_display_source
		from xpra.x11.gtk_x11.gdk_bindings import init_x11_filter
		from xpra.x11.bindings.window_bindings import X11WindowBindings  #pylint: disable=no-name-in-module
		from xpra.os_util import is_Wayland
		if not is_Wayland():
			#x11 focus events:
			gdk_win = window.get_window()
			xid = gdk_win.get_xid()
			init_gdk_display_source()
			os.environ["XPRA_X11_DEBUG_EVENTS"] = "FocusIn,FocusOut"
			init_x11_filter()
			with xlog:
				X11WindowBindings().selectFocusChange(xid)

	Gtk.main()
	return 0

if __name__ == "__main__":
	main()
