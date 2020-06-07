#!/usr/bin/env python
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pylint: disable=wrong-import-position

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib

from xpra.util import (
	MOVERESIZE_DIRECTION_STRING, MOVERESIZE_SIZE_TOPLEFT, MOVERESIZE_SIZE_TOP, \
	MOVERESIZE_SIZE_TOPRIGHT, MOVERESIZE_SIZE_RIGHT, MOVERESIZE_SIZE_BOTTOMRIGHT, \
	MOVERESIZE_SIZE_BOTTOM, MOVERESIZE_SIZE_BOTTOMLEFT, MOVERESIZE_SIZE_LEFT, \
	MOVERESIZE_MOVE, MOVERESIZE_CANCEL,
	)
from xpra.gtk_common.gtk_util import add_close_accel
from xpra.platform import program_context


width = 400
height = 200
def make_window():
	window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
	window.set_title("Window Move Resize")
	window.set_size_request(width, height)
	window.connect("delete_event", Gtk.main_quit)
	window.realize()
	root = window.get_window().get_screen().get_root_window()

	def initiate(x_root, y_root, direction, button, source_indication):
		#print("initiate%s" % str((x_root, y_root, direction, button, source_indication)))
		from xpra.x11.gtk_x11.gdk_display_source import init_gdk_display_source
		init_gdk_display_source()
		from xpra.x11.bindings.core_bindings import X11CoreBindings					#@UnresolvedImport
		from xpra.x11.bindings.window_bindings import constants, X11WindowBindings  #@UnresolvedImport
		event_mask = constants["SubstructureNotifyMask"] | constants["SubstructureRedirectMask"]
		root_xid = root.get_xid()
		xwin = window.get_window().get_xid()
		X11Core = X11CoreBindings()
		X11Core.UngrabPointer()
		X11Window = X11WindowBindings()
		X11Window.sendClientMessage(root_xid, xwin, False, event_mask, "_NET_WM_MOVERESIZE",
			  x_root, y_root, direction, button, source_indication)

	def cancel():
		initiate(0, 0, MOVERESIZE_CANCEL, 0, 1)


	table = Gtk.Table(n_rows=3, n_columns=3, homogeneous=True)

	FILL = Gtk.AttachOptions.FILL
	EXPAND = Gtk.AttachOptions.EXPAND
	btn = Gtk.Button(label="initiate move")
	table.attach(btn, 1, 2, 1, 2, xoptions=FILL, yoptions=FILL)
	def initiate_move(*_args):
		cancel()
		pos = root.get_pointer()
		source_indication = 1	#normal
		button = 1
		direction = MOVERESIZE_MOVE
		initiate(pos.x, pos.y, direction, button, source_indication)
		GLib.timeout_add(5*1000, cancel)
	btn.connect('button-press-event', initiate_move)

	def btn_callback(btn, event, direction):
		cancel()
		x, y = root.get_pointer()[:2]
		source_indication = 1	#normal
		button = 1
		initiate(x, y, direction, button, source_indication)
		GLib.timeout_add(5*1000, cancel)
	def add_button(x, y, direction):
		btn = Gtk.Button(label=MOVERESIZE_DIRECTION_STRING[direction])
		table.attach(btn, x, x+1, y, y+1, xoptions=EXPAND|FILL, yoptions=EXPAND|FILL)
		btn.connect('button-press-event', btn_callback, direction)

	for x,y,direction in (
						(0, 0, MOVERESIZE_SIZE_TOPLEFT),
						(1, 0, MOVERESIZE_SIZE_TOP),
						(2, 0, MOVERESIZE_SIZE_TOPRIGHT),
						(0, 1, MOVERESIZE_SIZE_LEFT),
						(1, 1, MOVERESIZE_MOVE),
						(2, 1, MOVERESIZE_SIZE_RIGHT),
						(0, 2, MOVERESIZE_SIZE_BOTTOMLEFT),
						(1, 2, MOVERESIZE_SIZE_BOTTOM),
						(2, 2, MOVERESIZE_SIZE_BOTTOMRIGHT),
							):
		add_button(x, y, direction)

	window.add(table)
	return window

def main():
	with program_context("initiate-moveresize", "Initiate Move-Resize"):
		w = make_window()
		w.show_all()
		add_close_accel(w, Gtk.main_quit)
		Gtk.main()
		return 0


if __name__ == "__main__":
	main()
