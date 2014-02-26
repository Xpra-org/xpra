#!/usr/bin/env python

import cairo
from gi.repository import Gtk, Gdk, GLib   #@UnresolvedImport

class TransparentColorWindow(Gtk.Window):

    def __init__(self):
        super(TransparentColorWindow, self).__init__()
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_default_size(320, 320)
        self.set_app_paintable(True)
        self.set_events(Gdk.EventMask.KEY_PRESS_MASK)
        self.connect("key_press_event", self.on_key_press)
        self.counter = 0
        self.increase = False
        self.connect("draw", self.area_draw)
        self.connect("destroy", Gtk.main_quit)
        self.show_all()
        GLib.timeout_add(50, self.repaint)

    def on_key_press(self, *args):
        self.increase = not self.increase

    def repaint(self):
        if self.increase:
            self.counter += 1
            self.queue_draw()
        return True

    def area_draw(self, widget, cr):
        cr.set_font_size(32)
        #Clear everything:
        cr.set_operator(cairo.OPERATOR_CLEAR)
        w, h = widget.get_size()
        cr.rectangle(0, 0, w, h)
        cr.fill()

        def paint_block(x, y, w, h, Rm=1.0, Gm=1.0, Bm=1.0, label=""):
            bw = float(w)/16
            bh = float(h)/16
            cr.set_operator(cairo.OPERATOR_SOURCE)
            for i in range(256):
                v = ((self.counter+i) % 256) / 256.0
                R = Rm * v
                G = Gm * v
                B = Bm * v
                cr.set_source_rgb(R, G, B)
                rx, ry, rw, rh = x+(i%16)*bw, y+(i//16)*bh, bw, bh
                cr.rectangle(rx, ry, rw, rh)
                #print("rectangle(%s, %s, %s, %s) alpha=%s" % (rx, ry, rw, rh, alpha))
                cr.fill()
            if label:
                cr.set_source_rgb(1, 1, 1)
                cr.move_to(x+w/2-12, y+h/2+8)
                cr.show_text(label)

        #Red block
        paint_block(0, 0, w/2, h/2, 1, 0, 0, "R")
        #Green block:
        paint_block(w/2, 0, w/2, h/2, 0, 1, 0, "G")
        #Blue block:
        paint_block(0, h/2, w/2, h/2, 0, 0, 1, "B")
        #Black Shade Block:
        paint_block(w/2, h/2, w/2, h/2, 1, 1, 1)

import signal
signal.signal(signal.SIGINT, lambda x,y : Gtk.main_quit)
TransparentColorWindow()
Gtk.main()
