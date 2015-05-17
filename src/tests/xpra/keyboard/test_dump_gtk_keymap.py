#!/usr/bin/env python

import pygtk
pygtk.require('2.0')
import gtk

keymap = gtk.gdk.keymap_get_default()

def print_keycodes():
	keycodes={}
	keynames={}
	for i in range(0, 2**8):
		entries = keymap.get_entries_for_keycode(i)
		if entries:
			keycodes[i] = entries
			names = []
			for entry in entries:
				keyval = entry[0]
				name = gtk.gdk.keyval_name(keyval)
				if name!="VoidSymbol":
					names.append(name)
			if len(names)>0:
				keynames[i] = names

	print("keycodes=%s" % keycodes)
	print("keynames=%s" % keynames)

def print_keycodes_with_names():
	keycodes=[]
	for i in range(0, 2**8):
		entries = keymap.get_entries_for_keycode(i)
		if entries:
			ext_entries = []
			for entry in entries:
				keyval, keycode, group, level = entry
				name = gtk.gdk.keyval_name(keyval)
				if keyval and name is None:
					print("name not found for keyval: %s, entry=%s" % (keyval, entry))
				ext_entries.append((keyval, name, keycode, group, level))
			keycodes.append(ext_entries)
	print("keycodes=%s" % keycodes)
	return keycodes

def main():
	print("keysyms=%s" % dir(gtk.keysyms))
	print("keymap=%s" % keymap)
	print("keymap.get_caps_lock_state()=%s" % keymap.get_caps_lock_state())
	print("keymap.get_direction()=%s" % keymap.get_direction())
	print("keymap.have_bidi_layouts()=%s" % keymap.have_bidi_layouts())
	print("keymap=%s" % str(dir(keymap)))

	print_keycodes()
	print("")
	print_keycodes_with_names()


if __name__ == "__main__":
	main()
