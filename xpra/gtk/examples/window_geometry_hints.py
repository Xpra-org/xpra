#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from xpra.os_util import gi_import
from xpra.gtk.window import add_close_accel
from xpra.gtk.widget import label
from xpra.gtk.pixbuf import get_icon_pixbuf

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GLib = gi_import("GLib")


class HintedWindows(Gtk.Window):

    def __init__(self, title=None, **kwargs):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title(title or "")
        add_close_accel(self, self.delete_event)
        self.connect("delete_event", self.delete_event)
        icon = get_icon_pixbuf("windows.png")
        if icon:
            self.set_icon(icon)

        if kwargs.pop("headerbar", False):
            hb = Gtk.HeaderBar()
            hb.set_show_close_button(True)
            hb.props.title = "HeaderBar example"
            self.set_titlebar(hb)

        da = Gtk.DrawingArea()
        self.add(da)

        def configure_event(_widget, event):
            self.set_title(title or "%ix%i" % (event.width, event.height))

        da.connect("configure-event", configure_event)

        geom = Gdk.Geometry()
        for attr in (
                "min_width", "min_height",
                "max_width", "max_height",
                "base_width", "base_height",
                "width_inc", "height_inc",
        ):
            v = kwargs.pop(attr, -1)
            setattr(geom, attr, v)
        value = 0
        if geom.min_width >= 0 or geom.min_height >= 0:
            value |= Gdk.WindowHints.MIN_SIZE
        if geom.max_width >= 0 or geom.max_height >= 0:
            value |= Gdk.WindowHints.MAX_SIZE
        if geom.base_width >= 0 or geom.base_height >= 0:
            value |= Gdk.WindowHints.BASE_SIZE
        if geom.width_inc >= 0 or geom.height_inc >= 0:
            value |= Gdk.WindowHints.RESIZE_INC
        hints = Gdk.WindowHints(value)
        width = kwargs.pop("width", -1)
        height = kwargs.pop("height", -1)
        self.set_default_size(width, height)
        self.set_geometry_hints(da, geom, hints)
        self.show_all()

    def delete_event(self, *_args) -> None:
        self.close()


class OptionWindow(Gtk.Window):

    def __init__(self, args=()):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("Window Size Constraints")
        self.connect("destroy", Gtk.main_quit)
        self.set_default_size(320, 200)
        self.set_border_width(20)
        self.set_position(Gtk.WindowPosition.CENTER)
        icon = get_icon_pixbuf("windows.png")
        if icon:
            self.set_icon(icon)

        grid = Gtk.Grid()
        grid.set_row_homogeneous(True)
        grid.set_column_homogeneous(True)

        def expand(widget):
            widget.set_hexpand(True)
            widget.set_vexpand(True)
            return widget

        def attach(widget, col, row):
            grid.attach(expand(widget), col, row, 1, 1)

        def l(s):  # noqa: E743
            return label(s)

        def line(row, *widgets):
            for i, widget in enumerate(widgets):
                attach(widget, i, row)

        def e() -> Gtk.Entry:
            entry = Gtk.Entry()
            entry.set_text("")
            return entry

        line(0, l("Size Property"), l("Width"), l("Height"))
        self.requested_width, self.requested_height = e(), e()
        line(1, l("Requested"), self.requested_width, self.requested_height)
        self.min_width, self.min_height = e(), e()
        line(2, l("Minimum"), self.min_width, self.min_height)
        self.max_width, self.max_height = e(), e()
        line(3, l("Maximum"), self.max_width, self.max_height)
        self.base_width, self.base_height = e(), e()
        line(4, l("Base"), self.base_width, self.base_height)
        self.inc_width, self.inc_height = e(), e()
        line(5, l("Increment"), self.inc_width, self.inc_height)
        self.headerbar = Gtk.CheckButton()
        line(6, l("Header Bar"), self.headerbar)
        line(7, l(""))
        btn = Gtk.Button()
        btn.set_label("Create")
        btn.connect("clicked", self.create)
        line(8, l(""), btn)
        self.add(grid)
        for i, entry in enumerate((
                self.requested_width, self.requested_height,
                self.min_width, self.min_height,
                self.max_width, self.max_height,
                self.base_width, self.base_height,
                self.inc_width, self.inc_height,
        )):
            if len(args) <= i:
                break
            try:
                int(args[i])
            except ValueError:
                pass
            else:
                entry.set_text(args[i])

    def create(self, *_args) -> None:
        kwargs = {}
        for prop, entry in {
            "width": self.requested_width,
            "height": self.requested_height,
            "min_width": self.min_width,
            "min_height": self.min_height,
            "max_width": self.max_width,
            "max_height": self.max_height,
            "base_width": self.base_width,
            "base_height": self.base_height,
            "inc_width": self.inc_width,
            "inc_height": self.inc_height,
        }.items():
            v = entry.get_text()
            if not v:
                continue
            try:
                kwargs[prop] = int(v)
            except ValueError:
                pass
        if self.headerbar.get_active():
            kwargs["headerbar"] = True
        w = HintedWindows(**kwargs)
        w.show_all()


def main() -> None:
    from xpra.platform import program_context
    with program_context("window-geometry-hints", "Window Geometry Hints"):
        w = OptionWindow(sys.argv[1:])
        add_close_accel(w, Gtk.main_quit)
        from xpra.gtk.util import quit_on_signals
        quit_on_signals("geometry hints test window")

        def show_with_focus() -> None:
            from xpra.platform.gui import force_focus
            force_focus()
            w.show_all()
            w.present()

        GLib.idle_add(show_with_focus)
        Gtk.main()


if __name__ == "__main__":
    main()
    sys.exit(0)
