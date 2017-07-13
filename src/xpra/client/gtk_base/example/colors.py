#!/usr/bin/env python
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import cairo

from xpra.gtk_common.gobject_compat import import_gtk, import_glib, is_gtk3
gtk = import_gtk()
gLib = import_glib()
from xpra.gtk_common.gtk_util import WIN_POS_CENTER, KEY_PRESS_MASK


class AnimatedColorWindow(gtk.Window):

    def __init__(self):
        super(AnimatedColorWindow, self).__init__()
        self.set_position(WIN_POS_CENTER)
        self.set_default_size(320, 320)
        self.set_app_paintable(True)
        self.set_events(KEY_PRESS_MASK)
        self.counter = 0
        self.increase = False
        if is_gtk3():
            self.connect("draw", self.area_draw)
        else:
            self.connect("expose-event", self.do_expose_event)
        self.connect("destroy", gtk.main_quit)
        self.connect("key_press_event", self.on_key_press)
        self.show_all()
        gLib.timeout_add(50, self.repaint)

    def do_expose_event(self, *args):
        cr = self.get_window().cairo_create()
        self.area_draw(self, cr)

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


def main():
    import signal
    signal.signal(signal.SIGINT, lambda x,y : gtk.main_quit)
    AnimatedColorWindow()
    gtk.main()


if __name__ == "__main__":
    main()
