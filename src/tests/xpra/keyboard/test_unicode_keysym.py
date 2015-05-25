#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>

from xpra.x11.bindings import posix_display_source      #@UnusedImport
from xpra.x11.bindings.keyboard_bindings import X11KeyboardBindings		#@UnresolvedImport
keyboard_bindings = X11KeyboardBindings()

def main():
	for x in ("2030", "0005", "0010", "220F", "2039", "2211", "2248", "FB01", "F8FF", "203A", "FB02", "02C6", "02DA", "02DC", "2206", "2044", "25CA"):
		#hex form:
		hk = keyboard_bindings.parse_keysym("0x"+x)
		print("keysym(0x%s)=%s" % (x, hk))
		#osx U+ form:
		uk = keyboard_bindings.parse_keysym("U+"+x)
		print("keysym(U+%s)=%s" % (x, uk))
		if hk:
			assert uk == hk, "failed to get unicode keysym %s" % x


if __name__ == "__main__":
	main()
