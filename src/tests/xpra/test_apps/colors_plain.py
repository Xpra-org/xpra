#!/usr/bin/env python

import cairo
import gi
gi.require_version('Gtk', '3.0')    #@UndefinedVariable

from gi.repository import Gtk, Gdk  #@UnresolvedImport

class TransparentColorWindow(Gtk.Window):

    def __init__(self):
        super(TransparentColorWindow, self).__init__()
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_default_size(320, 320)
        self.set_app_paintable(True)
        self.set_events(Gdk.EventMask.KEY_PRESS_MASK)
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

        def paint_block(x, y, w, h, R=255, G=255, B=255, label=""):
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_rgb(R, G, B)
            cr.rectangle(x, y, w, h)
            #print("rectangle(%s, %s, %s, %s) alpha=%s" % (rx, ry, rw, rh, alpha))
            cr.fill()
            if label:
                cr.set_source_rgb(1, 1, 1)
                cr.move_to(x+w/2-12, y+h/2+8)
                cr.show_text(label)

        #Red block
        paint_block(0, 0, w/2, h/2, 255, 0, 0, "R")
        #Green block:
        paint_block(w/2, 0, w/2, h/2, 0, 254, 0, "G")
        #Blue block:
        paint_block(0, h/2, w/2, h/2, 0, 0, 253, "B")
        #Black Shade Block:
        paint_block(w/2, h/2, w/2, h/2, 128, 128, 128)

import signal
signal.signal(signal.SIGINT, lambda x,y : Gtk.main_quit)
TransparentColorWindow()
Gtk.main()
