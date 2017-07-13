#!/usr/bin/env python
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import cairo

from xpra.gtk_common.gobject_compat import import_gtk, is_gtk3
gtk = import_gtk()
from xpra.gtk_common.gtk_util import WIN_POS_CENTER, KEY_PRESS_MASK


class TransparentColorWindow(gtk.Window):

    def __init__(self):
        super(TransparentColorWindow, self).__init__()
        self.set_position(WIN_POS_CENTER)
        self.set_default_size(320, 320)
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if is_gtk3():
            if visual and screen.is_composited():
                self.set_visual(visual)
            else:
                print("transparency not available!")
        else:
            colormap = screen.get_rgba_colormap()
            if colormap:
                self.set_colormap(colormap)
            else:
                print("transparency not available!")
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
        cr.set_font_size(32)
        #Clear everything:
        cr.save()
        cr.set_operator(cairo.OPERATOR_CLEAR)
        w, h = widget.get_size()
        cr.rectangle(0, 0, w, h)
        cr.fill()
        cr.restore()
        cr.set_operator(cairo.OPERATOR_SOURCE)

        def paint_block(label, x, y, r, g, b):
            #fill with colour
            cr.set_source_rgba(r, g, b, 1)
            cr.rectangle(x, y, x+w//2, y+h//2)
            cr.fill()
            #top and bottom thirds as a shade to transparent on the edges:
            shade_h = h//2//3
            for i in range(shade_h):
                alpha = i/float(shade_h)
                cr.set_source_rgba(r, g, b, alpha)
                cr.rectangle(x, y+i, x+w//2, 1)
                cr.fill()
                cr.set_source_rgba(r, g, b, alpha)
                cr.rectangle(x, y+h//2-i-1, x+w//2, 1)
                cr.fill()
            if label:
                cr.set_source_rgba(1, 1, 1, 1)
                cr.move_to(x+w//4-21*len(label)//2, y+h//4+8)
                cr.show_text(label)

        #Red block
        paint_block("RED", 0, 0, 1, 0, 0)
        #Green block:
        paint_block("GREEN", w//2, 0, 0, 1, 0)
        #Blue block:
        paint_block("BLUE", 0, h//2, 0, 0, 1)
        #Black block:
        paint_block("BLACK", w//2, h//2, 0, 0, 0)


def main():
    import signal
    signal.signal(signal.SIGINT, lambda x,y : gtk.main_quit)
    TransparentColorWindow()
    gtk.main()


if __name__ == "__main__":
    main()
