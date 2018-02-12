#!/usr/bin/env python

from xpra.gtk_common.gobject_compat import import_gtk, import_gdk
gtk = import_gtk()
gdk = import_gdk()
from xpra.gtk_common.gtk_util import (WINDOW_TOPLEVEL,
	WINDOW_STATE_WITHDRAWN, WINDOW_STATE_ICONIFIED, WINDOW_STATE_MAXIMIZED, WINDOW_STATE_STICKY,
	WINDOW_STATE_FULLSCREEN, WINDOW_STATE_ABOVE, WINDOW_STATE_BELOW)

def main():
	window = gtk.Window(WINDOW_TOPLEVEL)
	window.set_size_request(320, 500)
	window.connect("delete_event", gtk.main_quit)
	vbox = gtk.VBox(False, 0)

	def add_buttons(t1, cb1, t2, cb2):
		hbox = gtk.HBox(True, 10)
		b1 = gtk.Button(t1)
		def vcb1(*args):
			cb1()
		b1.connect('clicked', vcb1)
		hbox.pack_start(b1, expand=True, fill=False, padding=5)
		b2 = gtk.Button(t2)
		def vcb2(*args):
			cb2()
		b2.connect('clicked', vcb2)
		hbox.pack_start(b2, expand=True, fill=False, padding=5)
		vbox.pack_start(hbox, expand=False, fill=False, padding=2)

	add_buttons("maximize", window.maximize, "unmaximize", window.unmaximize)
	#fullscreen-monitors:
	hbox = gtk.HBox()
	fsm_entry = gtk.Entry()
	fsm_entry.set_text("0,0,0,0")
	hbox.add(fsm_entry)
	def set_fsm(*args):
		v = fsm_entry.get_text()
		strs = v.split(",")
		assert len(strs)==4, "the list of monitors must have 4 items!"
		monitors = [int(x) for x in strs]
		from xpra.platform.gui import set_fullscreen_monitors
		set_fullscreen_monitors(window.get_window(), monitors)
	set_fsm_btn = gtk.Button("Set Fullscreen Monitors")
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
				WINDOW_STATE_WITHDRAWN	: "withdrawn",
				WINDOW_STATE_ICONIFIED	: "iconified",
				WINDOW_STATE_MAXIMIZED	: "maximized",
				WINDOW_STATE_STICKY		: "sticky",
				WINDOW_STATE_FULLSCREEN	: "fullscreen",
				WINDOW_STATE_ABOVE		: "above",
				WINDOW_STATE_BELOW		: "below",
				}
		print("window_state(%s, %s)" % (widget, event))
		print("flags: %s" % [STATES[x] for x in STATES.keys() if x & event.new_window_state])
	window.connect("window-state-event", window_state)

	window.add(vbox)
	window.show_all()
	gtk.main()
	return 0


if __name__ == "__main__":
	main()
