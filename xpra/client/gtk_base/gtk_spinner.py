#!/usr/bin/env python
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# The code was taken from here:
# http://zetcode.com/gfx/pycairo/transparency/
# And is apparently GPL v2
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import math
import cairo
from gi.repository import GLib, Gtk

from xpra.client.spinner import cv


class Example(Gtk.Window):

    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        self.darea = Gtk.DrawingArea()
        self.darea.connect("expose-event", self.expose)
        self.add(self.darea)

        self.count = 0
        GLib.timeout_add(cv.SPEED, self.on_timer)

        self.set_title("Waiting")
        self.resize(250, 150)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("delete-event", Gtk.main_quit)
        self.show_all()


    def on_timer(self):
        self.count = self.count + 1
        if self.count >= cv.CLIMIT:
            self.count = 0
        self.darea.queue_draw()
        return True

    def expose(self, widget, _cr):
        cr = widget.window.cairo_create()
        cr.set_line_width(3)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        w, h = self.get_size()
        cr.translate(w/2, h/2)
        for i in range(cv.NLINES):
            cr.set_source_rgba(0, 0, 0, cv.trs[self.count%8][i])
            cr.move_to(0.0, -10.0)
            cr.line_to(0.0, -40.0)
            cr.rotate(math.pi/4)
            cr.stroke()


def main():
    Example()
    Gtk.main()


if __name__ == "__main__":
    main()
