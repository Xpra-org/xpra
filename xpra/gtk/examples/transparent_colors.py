#!/usr/bin/env python3
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import gi_import
from xpra.platform import program_context
from xpra.platform.gui import force_focus
from xpra.gtk.window import add_close_accel
from xpra.gtk.pixbuf import get_icon_pixbuf

from cairo import OPERATOR_CLEAR, OPERATOR_SOURCE  # pylint: disable=no-name-in-module

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GLib = gi_import("GLib")


class TransparentColorWindow(Gtk.Window):

    def __init__(self):
        super().__init__()
        self.set_title("Transparent Colors")
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_default_size(320, 320)
        icon = get_icon_pixbuf("encoding.png")
        if icon:
            self.set_icon(icon)
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
        self.area_draw()

    def area_draw(self, *_args):
        cr = self.get_window().cairo_create()
        cr.set_font_size(32)
        # Clear everything:
        cr.save()
        cr.set_operator(OPERATOR_CLEAR)
        alloc = self.get_allocated_size()[0]
        w, h = alloc.width, alloc.height
        cr.rectangle(0, 0, w, h)
        cr.fill()
        cr.restore()
        cr.set_operator(OPERATOR_SOURCE)

        def paint_block(label, x, y, r, g, b):
            # fill with colour
            cr.set_source_rgba(r, g, b, 1)
            cr.rectangle(x, y, x + w // 2, y + h // 2)
            cr.fill()
            # top and bottom thirds as a shade to transparent on the edges:
            shade_h = h // 2 // 3
            for i in range(shade_h):
                alpha = i / shade_h
                cr.set_source_rgba(r, g, b, alpha)
                cr.rectangle(x, y + i, x + w // 2, 1)
                cr.fill()
                cr.set_source_rgba(r, g, b, alpha)
                cr.rectangle(x, y + h // 2 - i - 1, x + w // 2, 1)
                cr.fill()
            if label:
                cr.set_source_rgba(1, 1, 1, 1)
                cr.move_to(x + w // 4 - 21 * len(label) // 2, y + h // 4 + 8)
                cr.show_text(label)

        # Red block
        paint_block("RED", 0, 0, 1, 0, 0)
        # Green block:
        paint_block("GREEN", w // 2, 0, 0, 1, 0)
        # Blue block:
        paint_block("BLUE", 0, h // 2, 0, 0, 1)
        # Black block:
        paint_block("BLACK", w // 2, h // 2, 0, 0, 0)


def main():
    from xpra.platform.gui import init, set_default_icon
    with program_context("transparent-colors", "Transparent Colors"):
        set_default_icon("encoding.png")
        init()

        from xpra.gtk.signals import quit_on_signals
        quit_on_signals("transparent colors test window")
        w = TransparentColorWindow()
        add_close_accel(w, Gtk.main_quit)
        GLib.idle_add(w.show_with_focus)
        Gtk.main()
        return 0


if __name__ == "__main__":
    main()
