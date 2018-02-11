#!/usr/bin/env python

from xpra.gtk_common.gobject_compat import import_glib, import_gtk, import_gdk
glib = import_glib()
gtk = import_gtk()
gdk = import_gdk()
from xpra.gtk_common.gtk_util import gtk_main, WINDOW_TOPLEVEL, GRAB_STATUS_STRING, WINDOW_EVENT_MASK, BUTTON_RELEASE_MASK


def main():
	window = gtk.Window(WINDOW_TOPLEVEL)
	window.set_size_request(600, 200)
	window.connect("delete_event", gtk.main_quit)
	window.add_events(WINDOW_EVENT_MASK)
	vbox = gtk.VBox(False, 0)
	hbox = gtk.HBox(False, 0)
	vbox.pack_start(hbox, expand=False, fill=False, padding=10)

	def keyevent_info(event):
		keyval = event.keyval
		keycode = event.hardware_keycode
		keyname = gdk.keyval_name(keyval)
		return "%i:%s" % (keycode, keyname)

	def key_pressed(_window, event):
		event_label.set_text("key_pressed: %s" % keyevent_info(event))
	window.connect("key-press-event", key_pressed)
	def key_released(_window, event):
		event_label.set_text("key_released: %s" % keyevent_info(event))
	window.connect("key-press-event", key_pressed)
	window.connect("key-release-event", key_pressed)

	def motion_notify(_window, event):
		event_label.set_text("motion: %i,%i" % (event.x_root, event.y_root))
	window.connect("motion-notify-event", motion_notify)


	grab_pointer_btn = gtk.Button("grab pointer")
	def grab_pointer(*args):
		action_label.set_text("grab_pointer%s" % str(args))
		def do_grab():
			event_mask = BUTTON_RELEASE_MASK
			v = gdk.pointer_grab(window.get_window(), False, event_mask, None, None, 0)
			#gdk.BUTTON_PRESS_MASK | gdk.BUTTON_RELEASE_MASK | gdk.KEY_PRESS_MASK \
			#gdk.KEY_RELEASE_MASK | gdk.ENTER_NOTIFY_MASK)
			# | gdk.ENTER_NOTIFY_MASK
			#gdk.ALL_EVENTS_MASK
			action_label.set_text("pointer_grab() returned %s" % GRAB_STATUS_STRING.get(v, v))
			glib.timeout_add(10*1000, gdk.pointer_ungrab, 0)
		print("will grab in 5 seconds!")
		glib.timeout_add(5*1000, do_grab)
	grab_pointer_btn.connect('clicked', grab_pointer)
	hbox.pack_start(grab_pointer_btn, expand=False, fill=False, padding=10)

	ungrab_pointer_btn = gtk.Button("ungrab pointer")
	def ungrab_pointer(*_args):
		v = gdk.pointer_ungrab(0)
		action_label.set_text("pointer_ungrab(0)=%s" % GRAB_STATUS_STRING.get(v, v))
		window.unmaximize()
	ungrab_pointer_btn.connect('clicked', ungrab_pointer)
	hbox.pack_start(ungrab_pointer_btn, expand=False, fill=False, padding=10)

	grab_keyboard_btn = gtk.Button("grab keyboard")
	def grab_keyboard(*_args):
		v = gdk.keyboard_grab(window.get_window(), True, 0)
		action_label.set_text("keyboard_grab(..)=%s" % GRAB_STATUS_STRING.get(v, v))
		glib.timeout_add(10*1000, gdk.keyboard_ungrab, 0)
	grab_keyboard_btn.connect('clicked', grab_keyboard)
	hbox.pack_start(grab_keyboard_btn, expand=False, fill=False, padding=10)

	ungrab_keyboard_btn = gtk.Button("ungrab keyboard")
	def ungrab_keyboard(*_args):
		v = gdk.keyboard_ungrab(0)
		action_label.set_text("keyboard_ungrab(0)=%s" % GRAB_STATUS_STRING.get(v, v))
	ungrab_keyboard_btn.connect('clicked', ungrab_keyboard)
	hbox.pack_start(ungrab_keyboard_btn, expand=False, fill=False, padding=10)

	vbox.add(gtk.Label("Last action:"))
	action_label = gtk.Label("")
	vbox.add(action_label)

	vbox.add(gtk.Label("Last event:"))
	event_label = gtk.Label("")
	vbox.add(event_label)

	window.add(vbox)
	window.show_all()
	gtk_main()
	return 0


if __name__ == "__main__":
	main()
