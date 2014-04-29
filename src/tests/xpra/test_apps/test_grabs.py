#!/usr/bin/env python

import gobject
import gtk


GRAB_DEFS = {
			gtk.gdk.GRAB_SUCCESS			: "SUCCESS",
			gtk.gdk.GRAB_ALREADY_GRABBED	: "ALREADY_GRABBED",
			gtk.gdk.GRAB_INVALID_TIME		: "INVALID_TIME",
			gtk.gdk.GRAB_NOT_VIEWABLE		: "NOT_VIEWABLE",
			gtk.gdk.GRAB_FROZEN				: "FROZEN"}

def main():
	window = gtk.Window(gtk.WINDOW_TOPLEVEL)
	window.set_size_request(600, 200)
	window.connect("delete_event", gtk.mainquit)
	vbox = gtk.VBox(False, 0)
	hbox = gtk.HBox(False, 0)
	vbox.pack_start(hbox, expand=False, fill=False, padding=10)

	grab_pointer_btn = gtk.Button("grab pointer")
	def grab_pointer(*args):
		print("grab_pointer%s" % str(args))
		def do_grab():
			v = gtk.gdk.pointer_grab(window.get_window(), owner_events=False, event_mask=gtk.gdk.BUTTON_RELEASE_MASK)
			#gtk.gdk.BUTTON_PRESS_MASK | gtk.gdk.BUTTON_RELEASE_MASK | gtk.gdk.KEY_PRESS_MASK \
			#gtk.gdk.KEY_RELEASE_MASK | gtk.gdk.ENTER_NOTIFY_MASK)
			# | gtk.gdk.ENTER_NOTIFY_MASK
			#gtk.gdk.ALL_EVENTS_MASK
			print("pointer_grab() returned %s" % GRAB_DEFS.get(v, v))
			gobject.timeout_add(10*1000, gtk.gdk.pointer_ungrab)
		print("will grab in 5 seconds!")
		gobject.timeout_add(5*1000, do_grab)
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
