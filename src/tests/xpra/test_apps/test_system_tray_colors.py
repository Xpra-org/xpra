#!/usr/bin/env python

import gtk
from gtk import gdk
import cairo

class StatusIcon:
    def __init__(self):
        self.statusicon = gtk.StatusIcon()
        self.counter = 0
        self.statusicon.connect("activate", self.quit_cb)
        self.statusicon.connect("popup-menu", self.quit_cb)
        self.statusicon.set_tooltip("StatusIcon Example")
        #generate tray image:
        s = 64
        w, h = s*2, s*2
        pixmap = gdk.Pixmap(gdk.get_default_root_window(), w, h)
        cr = pixmap.cairo_create()
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.fill()
        cr.set_operator(cairo.OPERATOR_SOURCE)
        for i, color in enumerate([(1, 0, 0, 1), (0, 1, 0, 1), (0, 0, 1, 1)]):
            cr.set_source_rgba(*color)
            cr.new_path()
            x = (i % 2) * s
            y = (i / 2) * s
            cr.move_to(x, y)
            cr.line_to(x + s, y)
            cr.line_to(x+s, y+s)
            cr.line_to(x, y+s)
            cr.close_path()
            cr.fill()
        pixbuf = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, True, 8, w, h)
        pixbuf.get_from_drawable(pixmap, pixmap.get_colormap(), 0, 0, 0, 0, w, h)
        self.statusicon.set_from_pixbuf(pixbuf)

    def quit_cb(self, *args):
        gtk.main_quit()


def main():
    StatusIcon()
    gtk.main()


if __name__ == "__main__":
    main()
