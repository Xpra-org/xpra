#!/usr/bin/env python
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform import program_context
from xpra.platform.gui import force_focus
from xpra.gtk_common.gtk_util import add_close_accel

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib	#pylint: disable=wrong-import-position


def make_window():
	window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
	window.set_title("Window States")
	window.set_size_request(320, 500)
	window.connect("delete_event", Gtk.main_quit)
	vbox = Gtk.VBox(False, 0)

	def add_buttons(t1, cb1, t2, cb2):
		hbox = Gtk.HBox(True, 10)
		b1 = Gtk.Button(label=t1)
		def vcb1(*_args):
			cb1()
		b1.connect('clicked', vcb1)
		hbox.pack_start(b1, expand=True, fill=False, padding=5)
		b2 = Gtk.Button(label=t2)
		def vcb2(*_args):
			cb2()
		b2.connect('clicked', vcb2)
		hbox.pack_start(b2, expand=True, fill=False, padding=5)
		vbox.pack_start(hbox, expand=False, fill=False, padding=2)

	add_buttons("maximize", window.maximize, "unmaximize", window.unmaximize)
	#fullscreen-monitors:
	hbox = Gtk.HBox()
	fsm_entry = Gtk.Entry()
	fsm_entry.set_text("0,0,0,0")
	hbox.add(fsm_entry)
	def set_fsm(*_args):
		v = fsm_entry.get_text()
		strs = v.split(",")
		assert len(strs)==4, "the list of monitors must have 4 items!"
		monitors = [int(x) for x in strs]
		from xpra.platform.gui import set_fullscreen_monitors
		set_fullscreen_monitors(window.get_window(), monitors)
	set_fsm_btn = Gtk.Button(label="Set Fullscreen Monitors")
	set_fsm_btn.connect("clicked", set_fsm)
	hbox.add(set_fsm_btn)
	vbox.pack_start(hbox, expand=False, fill=False, padding=2)
	add_buttons("fullscreen", window.fullscreen, "unfullscreen", window.unfullscreen)
	def decorate():
		window.set_decorated(True)
	def undecorate():
		window.set_decorated(False)
	add_buttons("decorate", decorate, "undecorate", undecorate)
	add_buttons("iconify", window.iconify, "deiconify", window.deiconify)
	def above():
		window.set_keep_above(True)
	def notabove():
		window.set_keep_above(False)
	add_buttons("keep above", above, "not above", notabove)
	def below():
		window.set_keep_below(True)
	def notbelow():
		window.set_keep_below(False)
	add_buttons("keep below", below, "not below", notbelow)
	add_buttons("stick", window.stick, "unstick", window.unstick)
	def skip_pager():
		window.set_skip_pager_hint(True)
	def notskip_pager():
		window.set_skip_pager_hint(False)
	add_buttons("skip pager", skip_pager, "not skip pager", notskip_pager)
	def skip_taskbar():
		window.set_skip_taskbar_hint(True)
	def notskip_taskbar():
		window.set_skip_taskbar_hint(False)
	add_buttons("skip taskbar", skip_taskbar, "not skip taskbar", notskip_taskbar)
	def shade():
		from xpra.platform.gui import set_shaded
		set_shaded(window.get_window(), True)
	def unshade():
		from xpra.platform.gui import set_shaded
		set_shaded(window.get_window(), False)
	add_buttons("shade", shade, "unshade", unshade)
	def modal():
		window.set_modal(True)
	def notmodal():
		window.set_modal(False)
	add_buttons("modal", modal, "not modal", notmodal)

	def window_state(widget, event):
		STATES = {
				Gdk.WindowState.WITHDRAWN	: "withdrawn",
				Gdk.WindowState.ICONIFIED	: "iconified",
				Gdk.WindowState.MAXIMIZED	: "maximized",
				Gdk.WindowState.STICKY		: "sticky",
				Gdk.WindowState.FULLSCREEN	: "fullscreen",
				Gdk.WindowState.ABOVE		: "above",
				Gdk.WindowState.BELOW		: "below",
				}
		print("window_state(%s, %s)" % (widget, event))
		print("flags: %s" % [STATES[x] for x in STATES.keys() if x & event.new_window_state])
	window.connect("window-state-event", window_state)
	window.add(vbox)
	return window

def main():
	with program_context("window-states", "Window States"):
		w = make_window()
		def show_with_focus():
			force_focus()
			w.show_all()
			w.present()
		add_close_accel(w, Gtk.main_quit)
		GLib.idle_add(show_with_focus)
		Gtk.main()
		return 0


if __name__ == "__main__":
	main()
