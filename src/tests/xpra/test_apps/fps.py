#!/usr/bin/env python

import cairo
import os
GTK3 = os.environ.get("GTK3", "1")=="1"
if GTK3:
    from gi.repository import Gtk as gtk, GLib as glib   #@UnresolvedImport @UnusedImport
else:
    import gtk, glib            #@Reimport
    from gtk import gdk


WIDTH, HEIGHT = 640, 640

class FPSWindow(gtk.Window):

    def __init__(self):
        super(FPSWindow, self).__init__()
        self.set_default_size(WIDTH, HEIGHT)
        self.set_app_paintable(True)
        self.counter = 0
        if GTK3:
            self.connect("draw", self.draw)
        else:
            self.connect("expose-event", self.do_expose_event)
        self.connect("destroy", gtk.main_quit)
        glib.timeout_add(10, self.repaint)


    def on_key_press(self, *args):
        pass

    def repaint(self):
        self.counter += 1
        if GTK3:
            self.queue_draw()
        else:
            window = self.get_window()
            window.invalidate_rect(gdk.Rectangle(0, 0, WIDTH, HEIGHT), False)
        return True

    def do_expose_event(self, widget, event):
        #cannot use self
        context = self.window.cairo_create()
        self.draw(self, context)

    def draw(self, widget, cr):
        w, h = widget.get_size()
        c = 0.2
        def paint_block(x, y, w, h, c, label):
            R = G = B = c
            cr.new_path()
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_rgb(R, G, B)
            cr.rectangle(x, y, w, h)
            cr.fill()
            #show label:
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

w = FPSWindow()
w.show_all()
gtk.main()
