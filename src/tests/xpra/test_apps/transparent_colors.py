#!/usr/bin/env python

import cairo
from gi.repository import Gtk   #@UnresolvedImport

class TransparentColorWindow(Gtk.Window):
    def __init__(self):
        super(TransparentColorWindow, self).__init__()
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_default_size(320, 320)
        screen = self.get_screen()
        self.visual = screen.get_rgba_visual()
        if self.visual and screen.is_composited():
            self.set_visual(self.visual)
        else:
            print("transparency not available!")

        self.set_app_paintable(True)
        self.connect("draw", self.area_draw)
        self.connect("destroy", Gtk.main_quit)
        self.show_all()

    def area_draw(self, widget, cr):
        cr.set_font_size(32)
        #Clear everything:
        cr.set_operator(cairo.OPERATOR_CLEAR)
        w, h = widget.get_size()
        cr.rectangle(0, 0, w, h)
        cr.fill()

        #Red block
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(1, 0, 0, 1)
        cr.rectangle(0, 0, w/2, h/2)
        cr.fill()
        cr.set_source_rgba(1, 1, 1, 1)
        cr.move_to(w/4-12, h/4+8)
        cr.show_text("R")
        #Green block:
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 1, 0, 1)
        cr.rectangle(w/2, 0, w/2, h/2)
        cr.fill()
        cr.set_source_rgba(1, 1, 1, 1)
        cr.move_to(w*3/4-12, h/4+8)
        cr.show_text("G")
        #Blue block:
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 1, 1)
        cr.rectangle(0, h/2, w/2, h/2)
        cr.fill()
        cr.set_source_rgba(1, 1, 1, 1)
        cr.move_to(w/4-12, h*3/4+8)
        cr.show_text("B")

        #Transparent Block:
        cr.set_operator(cairo.OPERATOR_SOURCE)
        bx = w/2
        by = h/2
        bw = float(w)/2/16
        bh = float(h)/2/16
        #print("bx=%s, by=%s, bw=%s, bh=%s" % (bx, by, bw, bh))
        for i in range(256):
            alpha = float(i+1)/256.0
            cr.set_source_rgba(1, 1, 1, alpha)
            rx, ry, rw, rh = bx+(i%16)*bw, by+(i//16)*bh, bw, bh
            cr.rectangle(rx, ry, rw, rh)
            #print("rectangle(%s, %s, %s, %s) alpha=%s" % (rx, ry, rw, rh, alpha))
            cr.fill()

TransparentColorWindow()
Gtk.main()
