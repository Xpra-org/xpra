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


class TransparentWindow(Gtk.Window):

    def __init__(self):
        super().__init__()
        self.set_title("Window Transparency")
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_default_size(320, 320)
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual and screen.is_composited():
            self.set_visual(visual)
        else:
            print("transparency not available!")
        self.set_app_paintable(True)
        self.set_events(Gdk.EventMask.KEY_PRESS_MASK)
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
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.0) # Transparent

        # Draw the background
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.paint()

        # Draw a circle
        alloc = widget.get_allocated_size()[0]
        width, height = alloc.width, alloc.height
        cr.set_source_rgba(1.0, 0.2, 0.2, 0.6)
        # Python <2.4 doesn't have conditional expressions
        if width < height:
            radius = width/2 - 0.8
        else:
            radius = height/2 - 0.8

        cr.arc(width/2, height/2, radius, 0, 2.0*3.14)
        cr.fill()
        cr.stroke()

def main():
    from xpra.platform.gui import init, set_default_icon
    with program_context("transparent-window", "Transparent Window"):
        set_default_icon("windows.png")
        init()

        import signal
        def signal_handler(*_args):
            Gtk.main_quit()
        signal.signal(signal.SIGINT, signal_handler)
        w = TransparentWindow()
        add_close_accel(w, Gtk.main_quit)
        GLib.idle_add(w.show_with_focus)
        Gtk.main()
        return 0


if __name__ == "__main__":
    main()
