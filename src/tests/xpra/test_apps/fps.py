#!/usr/bin/env python

import cairo
from gi.repository import Gtk, Gdk, GLib   #@UnresolvedImport

class TransparentColorWindow(Gtk.Window):

    def __init__(self):
        super(TransparentColorWindow, self).__init__()
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_default_size(640, 640)
        self.set_app_paintable(True)
        self.set_events(Gdk.EventMask.KEY_PRESS_MASK)
        self.connect("key_press_event", self.on_key_press)
        self.counter = 0
        self.connect("draw", self.draw)
        self.connect("destroy", Gtk.main_quit)
        GLib.timeout_add(10, self.repaint)


    def on_key_press(self, *args):
        pass

    def repaint(self):
        self.counter += 1
        self.queue_draw()
        return True

    def draw(self, widget, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        w, h = widget.get_size()
        c = 0.2
        def paint_block(x, y, w, h, c, label=""):
            R = G = B = c
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_rgb(R, G, B)
            cr.rectangle(x, y, w, h)
            cr.fill()
            if label:
                cr.set_source_rgb(1, 1, 1)
                cr.move_to(x+w/2-12, y+h/2+8)
                cr.show_text(label)

        #always paint top-left block in red or black
        div2 = self.counter%2==0
        div4 = self.counter%4==0
        div8 = self.counter%8==0
        div16 = self.counter%16==0
        paint_block(0, 0, w//2, h//2, div2*c, "1")
        if div2:        #half-rate
            #paint top-right block in green or black
            paint_block(w//2, 0, w//2, h//2, div4*c, "1/2")
        if div4:        #quarter rate
            #paint bottom-left block in blue or black 
            paint_block(0, h//2, w//2, h//2, div8*c, "1/4")
        if div8:        #one-eigth rate
            #paint bottom-right block in white or black
            paint_block(w//2, h//2, w//2, h//2, div16*c, "1/8")

w = TransparentColorWindow()
w.show_all()
Gtk.main()
