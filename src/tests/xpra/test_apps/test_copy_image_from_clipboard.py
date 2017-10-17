#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>

import sys
import pygtk
pygtk.require('2.0')
import gtk
import glib

def main():
    clipboard = gtk.clipboard_get()
    def request_image():
        image = clipboard.wait_for_image()
        print("image=%s" % image)
        return True
    glib.timeout_add(1000, request_image)
    gtk.main()

if __name__ == "__main__":
    main()
    sys.exit(0)
