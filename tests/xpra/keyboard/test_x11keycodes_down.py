#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@xpra.org>

import time
from xpra.x11.bindings import posix_display_source      #@UnusedImport
from xpra.x11.bindings.keyboard_bindings import X11KeyboardBindings		#@UnresolvedImport
keyboard_bindings = X11KeyboardBindings()

def main():
	while True:
		down = keyboard_bindings.get_keycodes_down()
		print("down=%s" % down)
		time.sleep(1)


if __name__ == "__main__":
	main()
