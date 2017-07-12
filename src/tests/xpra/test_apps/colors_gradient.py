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
        ww, wh = widget.get_size()
        cr.rectangle(0, 0, ww, wh)
        cr.fill()
        cr.restore()

        c = 8

        def paint_block(x, y, w, h, R=255, G=255, B=255, label=""):
            cr.set_operator(cairo.OPERATOR_SOURCE)
            for i in range(w):
                v = float(i)/float(w)
                cr.save()
                r = max(0, float(R)*v/255.0)
                g = max(0, float(G)*v/255.0)
                b = max(0, float(B)*v/255.0)
                cr.set_source_rgb(r, g, b)
                cr.rectangle(x+i, y, 1, h)
                cr.fill()
                cr.restore()
            if label:
                cr.set_font_size(32)
                cr.set_source_rgb(1, 1, 1)
                cr.move_to(x+w//2-12, y+wh//(c*2)+8)
                cr.show_text(label)

        #Red block
        paint_block(0, 0,       ww, wh/c,   255, 0, 0, "R")
        #Green block:
        paint_block(0, wh//c,   ww, 2*wh/c, 0, 254, 0, "G")
        #Blue block:
        paint_block(0, 2*wh//c, ww, 3*wh/c, 0, 0, 253, "B")
        #Black Shade Blocks:
        paint_block(0, 3*wh//c, ww, 4*wh/c,     255, 255, 255)
        paint_block(0, 4*wh//c, ww, 5*wh/c,     127, 127, 127)
        paint_block(0, 5*wh//c, ww, 6*wh/c,     63, 63, 63)
        paint_block(0, 6*wh//c, ww, 7*wh/c,     31, 31, 31)
        paint_block(0, 7*wh//c, ww, 8*wh/c,     15, 15, 15)

import signal
signal.signal(signal.SIGINT, lambda x,y : Gtk.main_quit)
TransparentColorWindow()
Gtk.main()
