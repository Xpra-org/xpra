#!/usr/bin/env python

import gtk
from gtk import gdk
import cairo
import gobject

class TestWindow(gtk.Window):

    def __init__(self):
        gtk.Window.__init__(self, gtk.WINDOW_TOPLEVEL)
        self.set_size_request(128, 128)
        self.counter = 0
        self.rotate = False
        def set_icon():
            #generate window icon image:
            if not self.rotate:
                return True
            s = 64
            w, h = s*2, s*2
            pixmap = gdk.Pixmap(gdk.get_default_root_window(), w, h)
            cr = pixmap.cairo_create()
            cr.set_operator(cairo.OPERATOR_CLEAR)
            cr.fill()
            cr.set_operator(cairo.OPERATOR_SOURCE)
            v = (self.counter % 256 / 255.0)
            self.counter += 10
            for i, color in enumerate([(1, 0, 0, 1), (0, 1, 0, 1), (0, 0, 1, 1), (v, v, v, v)]):
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
            self.set_icon(pixbuf)
            print("set icon to %s" % int(255*v))
            return True
        #how quickly we change the icon
        DELAY = 100
        gobject.timeout_add(DELAY, set_icon)
        self.connect("delete_event", self.quit_cb)
        self.set_events(gdk.KEY_PRESS_MASK)
        self.connect("key_press_event", self.on_key_press)
        self.show_all()

    def on_key_press(self, *_args):
        self.rotate = not self.rotate

    def quit_cb(self, *_args):
        gtk.main_quit()


def main():
    TestWindow()
    gtk.main()


if __name__ == "__main__":
    main()
