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
from gi.repository import GLib, Gtk, Gdk


class AnimatedColorWindow(Gtk.Window):

    def __init__(self):
        super().__init__()
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_default_size(320, 320)
        self.set_app_paintable(True)
        self.set_events(Gdk.EventMask.KEY_PRESS_MASK | Gdk.EventMask.BUTTON_PRESS_MASK)
        self.counter = 0
        self.increase = True
        self.last_event = None
        self.set_title("Animated Colors")
        drawing_area = Gtk.DrawingArea()
        drawing_area.connect("draw", self.area_draw)
        self.add(drawing_area)
        self.connect("destroy", Gtk.main_quit)
        self.connect("key_press_event", self.on_press)
        self.connect("button_press_event", self.on_press)
        GLib.timeout_add(50, self.repaint)

    def show_with_focus(self):
        force_focus()
        self.show_all()
        super().present()

    def do_expose_event(self, *_args):
        cr = self.get_window().cairo_create()
        self.area_draw(self, cr)

    def on_press(self, _window, event):
        if event==self.last_event:
            return
        self.last_event = event
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
        alloc = widget.get_allocated_size()[0]
        w, h = alloc.width, alloc.height
        cr.rectangle(0, 0, w, h)
        cr.fill()

        def paint_block(x, y, w, h, Rm=1.0, Gm=1.0, Bm=1.0, label=""):
            bw = w/16
            bh = h/16
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
    from xpra.platform.gui import init, set_default_icon
    with program_context("colors", "Colors"):
        set_default_icon("encoding.png")
        init()

        import signal
        def signal_handler(*_args):
            Gtk.main_quit()
        signal.signal(signal.SIGINT, signal_handler)
        w = AnimatedColorWindow()
        add_close_accel(w, Gtk.main_quit)
        GLib.idle_add(w.show_with_focus)
        Gtk.main()
        return 0


if __name__ == "__main__":
    main()
