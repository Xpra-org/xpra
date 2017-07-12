#!/usr/bin/env python

import cairo
import gi
gi.require_version('Gtk', '3.0')    #@UndefinedVariable

from gi.repository import Gtk, Gdk  #@UnresolvedImport

class TransparentColorWindow(Gtk.Window):

    def __init__(self):
        super(TransparentColorWindow, self).__init__()
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_default_size(1024, 768)
        self.set_app_paintable(True)
        self.set_events(Gdk.EventMask.KEY_PRESS_MASK)
        self.connect("draw", self.area_draw)
        self.connect("destroy", Gtk.main_quit)
        self.show_all()

    def area_draw(self, widget, cr):
        #Clear everything:
        cr.save()
        cr.set_operator(cairo.OPERATOR_CLEAR)
        w, h = widget.get_size()
        cr.rectangle(0, 0, w, h)
        cr.fill()
        cr.restore()

        count = 10
        self.index = 0
        bh = h//count
        def paint_block(R=255, G=255, B=255, label=""):
            y = h*self.index//count
            self.index += 1
            cr.set_operator(cairo.OPERATOR_SOURCE)
            for i in range(w):
                v = float(i)/float(w)
                cr.save()
                r = max(0, float(R)*v/255.0)
                g = max(0, float(G)*v/255.0)
                b = max(0, float(B)*v/255.0)
                cr.set_source_rgb(r, g, b)
                cr.rectangle(i, y, 1, bh)
                cr.fill()
                cr.restore()
            if label:
                cr.set_font_size(32)
                cr.set_source_rgb(1, 1, 1)
                cr.move_to(w//2-12, y+bh//2+8)
                cr.show_text(label)

        paint_block(255, 0, 0, "R")
        paint_block(0, 254, 0, "G")
        paint_block(0, 0, 253, "B")
        paint_block(0, 252, 252, "C")
        paint_block(251, 0, 251, "M")
        paint_block(251, 251, 0, "Y")
        #Black Shade Blocks:
        paint_block(255, 255, 255)
        paint_block(127, 127, 127)
        paint_block(63, 63, 63)
        paint_block(31, 31, 31)
        paint_block(15, 15, 15)

import signal
signal.signal(signal.SIGINT, lambda x,y : Gtk.main_quit)
TransparentColorWindow()
Gtk.main()
