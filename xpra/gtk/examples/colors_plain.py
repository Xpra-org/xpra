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


class ColorPlainWindow(Gtk.Window):

    def __init__(self):
        super().__init__()
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_default_size(320, 320)
        self.set_app_paintable(True)
        self.set_events(Gdk.EventMask.KEY_PRESS_MASK)
        self.set_title("Colors")
        icon = get_icon_pixbuf("encoding.png")
        if icon:
            self.set_icon(icon)
        drawing_area = Gtk.DrawingArea()
        drawing_area.connect("draw", self.area_draw)
        self.add(drawing_area)
        self.connect("destroy", Gtk.main_quit)

    def show_with_focus(self) -> None:
        force_focus()
        self.show_all()
        super().present()

    def area_draw(self, _area, cr) -> None:
        cr.set_font_size(32)
        # Clear everything:
        cr.set_operator(OPERATOR_CLEAR)
        alloc = self.get_allocated_size()[0]
        w, h = alloc.width, alloc.height
        cr.rectangle(0, 0, w, h)
        cr.fill()

        def paint_block(x, y, w, h, R=255, G=255, B=255, label="") -> None:
            cr.set_operator(OPERATOR_SOURCE)
            cr.set_source_rgb(R, G, B)
            cr.rectangle(x, y, w, h)
            # print("rectangle(%s, %s, %s, %s) alpha=%s" % (rx, ry, rw, rh, alpha))
            cr.fill()
            if label:
                cr.set_source_rgb(1, 1, 1)
                cr.move_to(x + w / 2 - 12, y + h / 2 + 8)
                cr.show_text(label)

        # Red block
        paint_block(0, 0, w / 2, h / 2, 255, 0, 0, "R")
        # Green block:
        paint_block(w / 2, 0, w / 2, h / 2, 0, 254, 0, "G")
        # Blue block:
        paint_block(0, h / 2, w / 2, h / 2, 0, 0, 253, "B")
        # Black Shade Block:
        paint_block(w / 2, h / 2, w / 2, h / 2, 128, 128, 128)


def main() -> None:
    from xpra.gtk.util import quit_on_signals
    with program_context("colors-plain", "Colors Plain"):
        quit_on_signals("colors test window")
        w = ColorPlainWindow()
        add_close_accel(w, Gtk.main_quit)
        GLib.idle_add(w.show_with_focus)
        Gtk.main()


if __name__ == "__main__":
    main()
