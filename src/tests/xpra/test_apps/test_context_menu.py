#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>

import sys
import pygtk
pygtk.require('2.0')
import gtk


class TestForm(object):

    def    __init__(self):
        self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
        self.window.connect("destroy", gtk.main_quit)
        self.window.set_default_size(320, 200)
        self.window.set_border_width(20)

        entry = gtk.Entry()
        entry.set_text("hello")

        self.window.add(entry)
        self.window.show_all()


def main():
    TestForm()
    gtk.main()


if __name__ == "__main__":
    main()
    sys.exit(0)
