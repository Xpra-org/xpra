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
        self.set_position(WIN_POS_CENTER)
        self.set_default_size(1024, 768)
        self.set_app_paintable(True)
        self.set_events(KEY_PRESS_MASK)
        if is_gtk3():
            self.connect("draw", self.area_draw)
        else:
            self.connect("expose-event", self.do_expose_event)
        self.connect("destroy", gtk.main_quit)
        self.show_all()

    def do_expose_event(self, *args):
        cr = self.get_window().cairo_create()
        self.area_draw(self, cr)

    def area_draw(self, widget, cr):
        #Clear everything:
        cr.save()
        cr.set_operator(cairo.OPERATOR_CLEAR)
        w, h = widget.get_size()
        cr.rectangle(0, 0, w, h)
        cr.fill()
        cr.restore()

        count = 11
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
        paint_block(0, 0, 0, "K")
        #Black Shade Blocks:
        paint_block(255, 255, 255)
        paint_block(127, 127, 127)
        paint_block(63, 63, 63)
        paint_block(31, 31, 31)
        paint_block(15, 15, 15)


def main():
    import signal
    signal.signal(signal.SIGINT, lambda x,y : gtk.main_quit)
    ColorGradientWindow()
    gtk.main()


if __name__ == "__main__":
    main()
