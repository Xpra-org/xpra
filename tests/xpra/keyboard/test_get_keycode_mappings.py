#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@xpra.org>

from xpra.x11.bindings import posix_display_source      #@UnusedImport
from xpra.x11.bindings.keyboard_bindings import X11KeyboardBindings	    #@UnresolvedImport
keyboard_bindings = X11KeyboardBindings()


def main():
	mappings = keyboard_bindings.get_keycode_mappings()
	print("mappings=%s" % mappings)
	print("")
	for k,v in mappings.items():
		print("%s\t\t:\t%s" % (k, v))


if __name__ == "__main__":
	main()
