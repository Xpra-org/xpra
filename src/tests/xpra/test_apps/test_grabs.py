#!/usr/bin/env python

import gobject
import gtk

def main():
	window = gtk.Window(gtk.WINDOW_TOPLEVEL)
	window.set_size_request(600, 200)
	window.connect("delete_event", gtk.mainquit)
	vbox = gtk.VBox(False, 0)
	hbox = gtk.HBox(False, 0)
	vbox.pack_start(hbox, expand=False, fill=False, padding=10)

	grab_pointer_btn = gtk.Button("grab pointer")
	def grab_pointer(*args):
		gtk.gdk.pointer_grab(window.get_window())
		gobject.timeout_add(10*1000, gtk.gdk.pointer_ungrab)
	grab_pointer_btn.connect('clicked', grab_pointer)
	hbox.pack_start(grab_pointer_btn, expand=False, fill=False, padding=10)

	ungrab_pointer_btn = gtk.Button("ungrab pointer")
	def ungrab_pointer(*args):
		gtk.gdk.pointer_ungrab()
		window.unmaximize()
	ungrab_pointer_btn.connect('clicked', ungrab_pointer)
	hbox.pack_start(ungrab_pointer_btn, expand=False, fill=False, padding=10)

	grab_keyboard_btn = gtk.Button("grab keyboard")
	def grab_keyboard(*args):
		gtk.gdk.keyboard_grab(window.get_window(), True)
		gobject.timeout_add(10*1000, gtk.gdk.keyboard_ungrab)
	grab_keyboard_btn.connect('clicked', grab_keyboard)
	hbox.pack_start(grab_keyboard_btn, expand=False, fill=False, padding=10)

	ungrab_keyboard_btn = gtk.Button("ungrab keyboard")
	def ungrab_keyboard(*args):
		gtk.gdk.keyboard_ungrab()
	ungrab_keyboard_btn.connect('clicked', ungrab_keyboard)
	hbox.pack_start(ungrab_keyboard_btn, expand=False, fill=False, padding=10)

	window.add(vbox)
	window.show_all()
	gtk.main()
	return 0


if __name__ == "__main__":
	main()
