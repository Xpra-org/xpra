#!/usr/bin/env python
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import cairo

from xpra.gtk_common.gobject_compat import import_gtk, is_gtk3
gtk = import_gtk()
from xpra.gtk_common.gtk_util import WIN_POS_CENTER, KEY_PRESS_MASK, add_close_accel


class ColorPlainWindow(gtk.Window):

    def __init__(self):
        super(ColorPlainWindow, self).__init__()
        self.set_position(WIN_POS_CENTER)
        self.set_default_size(320, 320)
        self.set_app_paintable(True)
        self.set_events(KEY_PRESS_MASK)
        if is_gtk3():
            self.connect("draw", self.area_draw)
        else:
            self.connect("expose-event", self.do_expose_event)
        self.connect("destroy", gtk.main_quit)
        self.show_all()

    def do_expose_event(self, *_args):
        cr = self.get_window().cairo_create()
        self.area_draw(self, cr)

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


def main():
    import signal
    def signal_handler(*_args):
        gtk.main_quit()
    signal.signal(signal.SIGINT, signal_handler)
    w = ColorPlainWindow()
    add_close_accel(w, gtk.main_quit)
    gtk.main()


if __name__ == "__main__":
    main()
