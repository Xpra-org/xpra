#!/usr/bin/env python

from cairo import OPERATOR_SOURCE  #pylint: disable=no-name-in-module

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib #pylint: disable=wrong-import-position


WIDTH, HEIGHT = 640, 640

class FPSWindow(Gtk.Window):

    def __init__(self):
        super().__init__()
        self.set_default_size(WIDTH, HEIGHT)
        self.set_app_paintable(True)
        self.counter = 0
        self.connect("draw", self._draw)
        self.connect("destroy", Gtk.main_quit)
        GLib.timeout_add(10, self.repaint)


    def on_key_press(self, *args):
        pass

    def repaint(self):
        self.counter += 1
        self.queue_draw()
        return True

    def _draw(self, widget, cr):
        c = 0.2
        def paint_block(x, y, w, h, div):
            split_h = self.counter//div % h
            #top half:
            if split_h>0:
                cr.new_path()
                cr.set_operator(OPERATOR_SOURCE)
                cr.set_source_rgb(c, c, c)
                cr.rectangle(x, y, w, split_h)
                cr.fill()
            #bottom half:
            if split_h<h:
                cr.new_path()
                cr.set_operator(OPERATOR_SOURCE)
                cr.set_source_rgb(0, 0, 0)
                cr.rectangle(x, y+split_h, w, h-split_h)
                cr.fill()
            #show label:
            cr.set_source_rgb(1, 1, 1)
            cr.move_to(x+w/2-12, y+h/2+8)
            cr.show_text("1/%s" % div)

        w, h = widget.get_size()
        paint_block(0, 0, w//2, h//2, 1)
        if self.counter%2==0:        #half-rate
            paint_block(w//2, 0, w//2, h//2, 2)
        if self.counter%4==0:        #quarter rate
            paint_block(0, h//2, w//2, h//2, 4)
        if self.counter%8==0:        #one-eigth rate
            paint_block(w//2, h//2, w//2, h//2, 8)

window = FPSWindow()
window.show_all()
Gtk.main()
