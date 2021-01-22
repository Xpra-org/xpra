#!/usr/bin/env python

import pygtk
pygtk.require('2.0')
import gtk


from xpra.x11.bindings import posix_display_source      #@UnusedImport
from xpra.x11.bindings.keyboard_bindings import X11KeyboardBindings		#@UnresolvedImport
keyboard_bindings = X11KeyboardBindings()
keycode_mappings = keyboard_bindings.get_keycode_mappings()
modifier_mappings = keyboard_bindings.get_modifier_mappings()


def keys_changed(*args):
	global keycode_mappings, modifier_mappings
	print("keys_changed(%s)" % str(args))
	new_keycode_mappings = keyboard_bindings.get_keycode_mappings()
	new_modifier_mappings = keyboard_bindings.get_modifier_mappings()
	if new_keycode_mappings!=keycode_mappings:
		print("modifier mappings have changed: %s" % new_modifier_mappings)
		modifier_mappings = new_modifier_mappings
	if new_keycode_mappings!=keycode_mappings:
		print("keycode mappings have changed: %s" % new_keycode_mappings)
		keycode_mappings = new_keycode_mappings

def main():
	keymap = gtk.gdk.keymap_get_default()
	print("keymap=%s" % keymap)
	keymap.connect("keys-changed", keys_changed)

	gtk.main()


if __name__ == "__main__":
	main()
