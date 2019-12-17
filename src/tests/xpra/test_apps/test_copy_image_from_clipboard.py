#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>

import sys
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib   #pylint: disable=wrong-import-position

def main():
    clipboard = Gtk.Clipboard.get(Gdk.Atom.intern("CLIPBOARD", False))
    def request_image():
        image = clipboard.wait_for_image()
        print("image=%s" % image)
        return True
    GLib.timeout_add(1000, request_image)
    Gtk.main()

if __name__ == "__main__":
    main()
    sys.exit(0)
