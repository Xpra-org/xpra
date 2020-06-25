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


class ColorPlainWindow(Gtk.Window):

    def __init__(self):
        super().__init__()
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_default_size(320, 320)
        self.set_app_paintable(True)
        self.set_events(Gdk.EventMask.KEY_PRESS_MASK)
        self.set_title("Colors")
        drawing_area = Gtk.DrawingArea()
        drawing_area.connect("draw", self.area_draw)
        self.add(drawing_area)
        self.connect("destroy", Gtk.main_quit)

    def show_with_focus(self):
        force_focus()
        self.show_all()
        super().present()

    def do_expose_event(self, *_args):
        cr = self.get_window().cairo_create()
        self.area_draw(self, cr)

    def area_draw(self, widget, cr):
        cr.set_font_size(32)
        #Clear everything:
        cr.set_operator(cairo.OPERATOR_CLEAR)
        alloc = widget.get_allocated_size()[0]
        w, h = alloc.width, alloc.height
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
    with program_context("colors-plain", "Colors Plain"):
        import signal
        def signal_handler(*_args):
            Gtk.main_quit()
        signal.signal(signal.SIGINT, signal_handler)
        w = ColorPlainWindow()
        add_close_accel(w, Gtk.main_quit)
        GLib.idle_add(w.show_with_focus)
        Gtk.main()


if __name__ == "__main__":
    main()
