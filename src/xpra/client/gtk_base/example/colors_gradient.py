#!/usr/bin/env python
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import cairo

from xpra.gtk_common.gobject_compat import import_gtk, is_gtk3
gtk = import_gtk()
from xpra.gtk_common.gtk_util import WIN_POS_CENTER, KEY_PRESS_MASK


class ColorGradientWindow(gtk.Window):

    def __init__(self):
        super(ColorGradientWindow, self).__init__()
        self.set_title("Color Gradient")
        self.set_position(WIN_POS_CENTER)
        self.set_default_size(1024, 768)
        self.set_app_paintable(True)
        self.set_events(KEY_PRESS_MASK)
        self.bpc = 16
        if is_gtk3():
            self.connect("draw", self.area_draw)
        else:
            self.connect("expose-event", self.do_expose_event)
        self.connect("configure_event", self.configure_event)
        #self.connect('resize', changed)
        self.connect("destroy", gtk.main_quit)
        self.connect("key_press_event", self.on_key_press)
        self.show_all()

    def configure_event(self, *args):
        self.queue_draw()

    def on_key_press(self, *args):
        self.bpc = ((self.bpc-2) % 16)+1
        self.queue_draw()

    def do_expose_event(self, *args):
        #print("do_expose_event")
        cr = self.get_window().cairo_create()
        self.area_draw(self, cr)

    def area_draw(self, widget, cr):
        cr.save()
        cr.set_operator(cairo.OPERATOR_CLEAR)
        w, h = widget.get_size()
        cr.rectangle(0, 0, w, h)
        cr.fill()
        cr.restore()

        blocks = 12
        bh = h//blocks
        M = 2**16-1
        mask = 0
        for i in range(16-self.bpc):
            mask = mask*2+1
        mask = 0xffff ^ mask
        def normv(v):
            assert 0<=v<=M
            iv = int(v) & mask
            return max(0, float(iv)/M)
        def paint_block(R=M, G=M, B=M, label=""):
            y = h*self.index//blocks
            self.index += 1
            cr.set_operator(cairo.OPERATOR_SOURCE)
            for i in range(w):
                v = float(i)/float(w)
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
        txt = "Clipped to %i bytes per pixel" % self.bpc
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
    import signal
    signal.signal(signal.SIGINT, lambda x,y : gtk.main_quit)
    ColorGradientWindow()
    gtk.main()


if __name__ == "__main__":
    main()
