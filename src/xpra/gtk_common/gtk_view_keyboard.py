#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>

import sys
import pygtk
pygtk.require('2.0')
import gtk
import pango
import gobject

from xpra.deque import maxdeque
from xpra.platform import get_icon, init


modifier_names = {
				  gtk.gdk.SHIFT_MASK	: "Shift",
				  gtk.gdk.LOCK_MASK		: "Lock",
				  gtk.gdk.CONTROL_MASK  : "Control",
				  gtk.gdk.MOD1_MASK		: "mod1",
				  gtk.gdk.MOD2_MASK		: "mod2",
				  gtk.gdk.MOD3_MASK		: "mod3",
				  gtk.gdk.MOD4_MASK		: "mod4",
				  gtk.gdk.MOD5_MASK		: "mod5"
				  }
short_modifier_names = {
				  gtk.gdk.SHIFT_MASK	: "S",
				  gtk.gdk.LOCK_MASK		: "L",
				  gtk.gdk.CONTROL_MASK  : "C",
				  gtk.gdk.MOD1_MASK		: "1",
				  gtk.gdk.MOD2_MASK		: "2",
				  gtk.gdk.MOD3_MASK		: "3",
				  gtk.gdk.MOD4_MASK		: "4",
				  gtk.gdk.MOD5_MASK		: "5"
				  }

class KeyboardStateInfoWindow:

	def	__init__(self):
		self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
		self.window.connect("destroy", self.destroy)
		self.window.set_default_size(540, 800)
		self.window.set_border_width(20)

		# Title
		vbox = gtk.VBox(False, 0)
		vbox.set_spacing(15)
		label = gtk.Label("Keyboard State")
		label.modify_font(pango.FontDescription("sans 13"))
		vbox.pack_start(label)

		self.modifiers = gtk.Label()
		vbox.add(self.modifiers)

		self.mouse = gtk.Label()
		vbox.add(self.mouse)

		self.keys = gtk.Label()
		fixed = pango.FontDescription('monospace 9')
		self.keys.modify_font(fixed)
		vbox.add(self.keys)

		self.window.add(vbox)
		self.window.show_all()
		gobject.timeout_add(100, self.populate_modifiers)

		self.key_events = maxdeque(maxlen=35)
		self.window.connect("key-press-event", self.key_press)
		self.window.connect("key-release-event", self.key_release)
		self.window.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.HAND2))

		icon = get_icon("keyboard.png")
		if icon:
			self.window.set_icon(icon)

	def populate_modifiers(self, *args):
		(x, y, current_mask) = gtk.gdk.get_default_root_window().get_pointer()
		self.mouse.set_text("%s %s" % (x, y))
		modifiers = self.mask_to_names(current_mask, modifier_names)
		self.modifiers.set_text(str(modifiers))
		return	True

	def mask_to_names(self, mask, names_dict):
		names = []
		for m,name in names_dict.items():
			if mask & m:
				names.append(name)
		return  names

	def key_press(self, _, event):
		self.add_key_event("down", event)

	def key_release(self, _, event):
		self.add_key_event("up", event)

	def add_key_event(self, etype, event):
		modifiers = self.mask_to_names(event.state, short_modifier_names)
		name = gtk.gdk.keyval_name(event.keyval)
		text = ""
		for v,l in ((etype, 5), (name, 24), (event.string, 4),
					(event.keyval, 10), (event.hardware_keycode, 10),
					(event.is_modifier, 2), (event.group, 2),
					(modifiers, -1)):
			s = str(v).replace("\n", "\\n").replace("\r", "\\r")
			if l>0:
				s = s.ljust(l)
			text += s
		self.key_events.append(text)
		self.keys.set_text("\n".join(self.key_events))

	def destroy(self, *args):
		gtk.main_quit()


def main():
	from xpra.gtk_common.gtk_util import set_application_name, set_prgname
	if sys.platform.startswith("win"):
		from xpra.win32 import set_redirect_output, set_log_filename
		set_redirect_output(True)
		set_log_filename("Keyboard_Test.log")
	init()
	set_prgname("Keyboard Test Tool")
	set_application_name("Keyboard Test Tool")
	KeyboardStateInfoWindow()
	gtk.main()


if __name__ == "__main__":
	main()
	sys.exit(0)
