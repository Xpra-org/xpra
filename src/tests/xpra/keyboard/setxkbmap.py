#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>

from xpra.x11.bindings import posix_display_source      #@UnusedImport
from xpra.x11.bindings.keyboard_bindings import X11KeyboardBindings		#@UnresolvedImport
keyboard_bindings = X11KeyboardBindings()

def main():
	import sys
	args = {}
	for known_arg in ("rules", "model", "layout", "variant", "options"):
		try:
			pos = sys.argv.index("-%s" % known_arg)
		except:
			continue
		if pos<len(sys.argv)-1:
			args[known_arg] = sys.argv[pos+1]
	if "-h" in sys.argv or "--help" in sys.argv or len(args)==0:
		print("%s: [-rules rules] [-model model] [-layout layout] [-variant variant] [-options options]" % sys.argv[0])
		sys.exit(1)
	#print("parsed command line arguments: %s" % str(args))
	rules = args.get("rules")
	model = args.get("model")
	layout = args.get("layout")
	variant = args.get("variant")
	options = args.get("options")
	keyboard_bindings.setxkbmap(rules, model, layout, variant, options)

if __name__ == "__main__":
	main()
