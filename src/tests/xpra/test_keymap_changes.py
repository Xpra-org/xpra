#!/usr/bin/env python

import pygtk
pygtk.require('2.0')
import gtk


from wimpiggy.lowlevel import get_keycode_mappings		#@UnresolvedImport
from wimpiggy.lowlevel import get_modifier_mappings		#@UnresolvedImport

keycode_mappings = get_keycode_mappings(gtk.gdk.get_default_root_window())
modifier_mappings = get_modifier_mappings()

def keys_changed(*args):
	global keycode_mappings, modifier_mappings
	print("keys_changed(%s)" % str(args))
	new_keycode_mappings = get_keycode_mappings(gtk.gdk.get_default_root_window())
	new_modifier_mappings = get_modifier_mappings()
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
