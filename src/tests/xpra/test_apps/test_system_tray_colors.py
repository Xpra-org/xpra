#!/usr/bin/env python

import cairo
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk,GdkPixbuf  #pylint: disable=wrong-import-position

class StatusIcon:
    def __init__(self):
        self.statusicon = Gtk.StatusIcon()
        self.counter = 0
        self.statusicon.connect("activate", self.quit_cb)
        self.statusicon.connect("popup-menu", self.quit_cb)
        self.statusicon.set_tooltip_text("StatusIcon Example")
        #generate tray image:
        s = 64
        w, h = s*2, s*2
        pixmap = Gdk.Pixmap(Gdk.get_default_root_window(), w, h)
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
        pixbuf = GdkPixbuf(Gdk.COLORSPACE_RGB, True, 8, w, h)
        pixbuf.get_from_drawable(pixmap, pixmap.get_colormap(), 0, 0, 0, 0, w, h)
        self.statusicon.set_from_pixbuf(pixbuf)

    def quit_cb(self, *args):
        Gtk.main_quit()


def main():
    StatusIcon()
    Gtk.main()


if __name__ == "__main__":
    main()
