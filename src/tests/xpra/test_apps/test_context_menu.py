#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>

import sys

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk   #pylint: disable=wrong-import-position


def main():
    window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
    window.connect("destroy", Gtk.main_quit)
    window.set_default_size(320, 200)
    window.set_border_width(20)

    entry = Gtk.Entry()
    entry.set_text("hello")

    window.add(entry)
    window.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
    sys.exit(0)
