#!/usr/bin/env python
# Copyright (C) 2017-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform import program_context
from xpra.platform.gui import force_focus
from xpra.gtk_common.gtk_util import add_close_accel

import cairo
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib



class ColorGradientWindow(Gtk.Window):

    def __init__(self):
        super().__init__()
        self.set_title("Color Bit Depth")
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_default_size(1024, 768)
        self.set_app_paintable(True)
        self.set_events(Gdk.EventMask.KEY_PRESS_MASK)
        self.bpc = 16
        drawing_area = Gtk.DrawingArea()
        drawing_area.connect("draw", self.area_draw)
        self.add(drawing_area)
        self.connect("configure_event", self.configure_event)
        #self.connect('resize', changed)
        self.connect("destroy", Gtk.main_quit)
        self.connect("key_press_event", self.on_key_press)

    def show_with_focus(self):
        force_focus()
        self.show_all()
        super().present()

    def configure_event(self, *_args):
        self.queue_draw()

    def on_key_press(self, _widget, key_event):
        if key_event.string == "-":
            self.bpc = ((self.bpc-2) % 16)+1
        else:
            self.bpc = (self.bpc%16)+1
        self.queue_draw()

    def do_expose_event(self, *_args):
        #print("do_expose_event")
        cr = self.get_window().cairo_create()
        self.area_draw(self, cr)

    def area_draw(self, widget, cr):
        cr.save()
        cr.set_operator(cairo.OPERATOR_CLEAR)
        alloc = widget.get_allocated_size()[0]
        w, h = alloc.width, alloc.height
        cr.rectangle(0, 0, w, h)
        cr.fill()
        cr.restore()

        blocks = 12
        bh = h//blocks
        M = 2**16-1
        mask = 0
        for _ in range(16-self.bpc):
            mask = mask*2+1
        mask = 0xffff ^ mask
        def normv(v):
            assert 0<=v<=M
            iv = int(v) & mask
            return max(0, iv/M)
        def paint_block(R=M, G=M, B=M, label=""):
            y = h*self.index//blocks
            self.index += 1
            cr.set_operator(cairo.OPERATOR_SOURCE)
            for i in range(w):
                v = i/w
                cr.save()
                r = normv(R*v)
                g = normv(G*v)
                b = normv(B*v)
                cr.set_source_rgb(r, g, b)
                cr.rectangle(i, y, 1, bh)
                cr.fill()
                cr.restore()
            if label:
                cr.set_font_size(32)
                cr.set_source_rgb(1, 1, 1)
                cr.move_to(w//2-12, y+bh//2+8)
                cr.show_text(label)

        #top block for title, all white:
        cr.save()
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(0, 0, w, bh)
        cr.fill()
        cr.restore()
        #title
        cr.set_font_size(32)
        cr.set_source_rgb(0, 0, 0)
        txt = "Clipped to %i bits per channel" % self.bpc
        cr.move_to(w//2-8*len(txt), bh//2+8)
        cr.show_text(txt)

        self.index = 1
        paint_block(M, 0, 0, "R")
        paint_block(0, M-1, 0, "G")
        paint_block(0, 0, M-2, "B")
        paint_block(0, M-3, M-3, "C")
        paint_block(M-4, 0, M-4, "M")
        paint_block(M-5, M-5, 0, "Y")
        paint_block(0, 0, 0, "K")
        #Black Shade Blocks:
        paint_block(M, M, M)
        paint_block(M//2, M//2, M//2)
        paint_block(M//4, M//4, M//4)
        paint_block(M//8, M//8, M//8)
        paint_block(M//16, M//16, M//16)


def main():
    from xpra.platform.gui import init, set_default_icon
    with program_context("colors-gradient", "Colors Gradient"):
        set_default_icon("encoding.png")
        init()

        import signal
        def signal_handler(*_args):
            Gtk.main_quit()
        signal.signal(signal.SIGINT, signal_handler)
        w = ColorGradientWindow()
        add_close_accel(w, Gtk.main_quit)
        GLib.idle_add(w.show_with_focus)
        Gtk.main()


if __name__ == "__main__":
    main()
