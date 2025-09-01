#!/usr/bin/env python3
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import gi_import
from xpra.platform import program_context
from xpra.platform.gui import force_focus
from xpra.gtk.window import add_close_accel
from xpra.gtk.pixbuf import get_icon_pixbuf

from cairo import OPERATOR_SOURCE  # pylint: disable=no-name-in-module

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GLib = gi_import("GLib")


class TransparentWindow(Gtk.Window):

    def __init__(self):
        super().__init__()
        self.set_title("Window Transparency")
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_default_size(320, 320)
        icon = get_icon_pixbuf("windows.png")
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

    def show_with_focus(self) -> None:
        force_focus()
        self.show_all()
        super().present()

    def area_draw(self, _area, cr) -> None:
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.0)  # Transparent
        # Draw the background
        cr.set_operator(OPERATOR_SOURCE)
        cr.paint()
        # Draw a circle
        alloc = self.get_allocated_size()[0]
        width, height = alloc.width, alloc.height
        cr.set_source_rgba(1.0, 0.2, 0.2, 0.6)
        radius = min(width, height) / 2 - 0.8
        cr.arc(width / 2, height / 2, radius, 0, 2.0 * 3.14)
        cr.fill()
        cr.stroke()


def main() -> int:
    from xpra.platform.gui import init, set_default_icon
    with program_context("transparent-window", "Transparent Window"):
        set_default_icon("windows.png")
        init()

        from xpra.gtk.util import quit_on_signals
        quit_on_signals("transparency test window")
        w = TransparentWindow()
        add_close_accel(w, Gtk.main_quit)
        GLib.idle_add(w.show_with_focus)
        Gtk.main()
        return 0


if __name__ == "__main__":
    main()
