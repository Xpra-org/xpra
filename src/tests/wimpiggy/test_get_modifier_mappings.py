#!/usr/bin/env python
# This file is part of Parti.
# Copyright (C) 2011, 2012 Antoine Martin <antoine@nagafix.co.uk>

import pygtk
pygtk.require('2.0')

from wimpiggy.lowlevel import get_modifier_mappings		#@UnresolvedImport

def main():
	mappings = get_modifier_mappings()
	print("mappings=%s" % mappings)

if __name__ == "__main__":
	main()
