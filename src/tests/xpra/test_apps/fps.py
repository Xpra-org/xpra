#!/usr/bin/env python

import os
import cairo

GTK3 = os.environ.get("GTK3", "1")=="1"
if GTK3:
    from gi.repository import Gtk as gtk, GLib as glib   #@UnresolvedImport @UnusedImport
else:
    import gtk, glib            #@Reimport @UnresolvedImport
    from gtk import gdk         #@UnresolvedImport


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
        def paint_block(x, y, w, h, div):
            split_h = self.counter//div % h
            #top half:
            if split_h>0:
                cr.new_path()
                cr.set_operator(cairo.OPERATOR_SOURCE)
                cr.set_source_rgb(c, c, c)
                cr.rectangle(x, y, w, split_h)
                cr.fill()
            #bottom half:
            if split_h<h:
                cr.new_path()
                cr.set_operator(cairo.OPERATOR_SOURCE)
                cr.set_source_rgb(0, 0, 0)
                cr.rectangle(x, y+split_h, w, h-split_h)
                cr.fill()
            #show label:
            cr.set_source_rgb(1, 1, 1)
            cr.move_to(x+w/2-12, y+h/2+8)
            cr.show_text("1/%s" % div)

        paint_block(0, 0, w//2, h//2, 1)
        if self.counter%2==0:        #half-rate
            paint_block(w//2, 0, w//2, h//2, 2)
        if self.counter%4==0:        #quarter rate
            paint_block(0, h//2, w//2, h//2, 4)
        if self.counter%8==0:        #one-eigth rate
            paint_block(w//2, h//2, w//2, h//2, 8)

w = FPSWindow()
w.show_all()
gtk.main()
