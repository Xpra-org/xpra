#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>

import os
import sys
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GdkPixbuf #pylint: disable=wrong-import-position

count = 0
def handle_owner_change(clipboard, event):
    global count
    print('clipboard.owner-change(%r, %r)' % (clipboard, event))
    #count += 1
    #if count > 1:
    #    sys.exit(0)

def main():
    assert os.path.exists(sys.argv[1])
    image = GdkPixbuf.Pixbuf.new_from_file(sys.argv[1])
    clipboard = Gtk.Clipboard.get(Gdk.Atom.intern("CLIPBOARD", False))
    clipboard.connect('owner-change', handle_owner_change)
    clipboard.set_image(image)
    clipboard.store()
    Gtk.main()

if __name__ == "__main__":
    main()
    sys.exit(0)
