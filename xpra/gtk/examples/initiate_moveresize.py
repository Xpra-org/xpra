#!/usr/bin/env python3
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import gi_import
from xpra.util.env import IgnoreWarningsContext
from xpra.common import MoveResize, MOVERESIZE_DIRECTION_STRING
from xpra.gtk.window import add_close_accel
from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.platform import program_context

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")

width = 400
height = 400


def make_window():
    window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
    window.set_title("Window Move Resize")
    window.set_position(Gtk.WindowPosition.CENTER)
    window.connect("delete_event", Gtk.main_quit)
    icon = get_icon_pixbuf("windows.png")
    if icon:
        window.set_icon(icon)

    def get_pointer():
        with IgnoreWarningsContext():
            return window.get_window().get_screen().get_root_window().get_pointer()

    def initiate(x_root: float, y_root: float, direction: MoveResize, button: int, source_indication: int):
        from xpra.x11.gtk.display_source import init_gdk_display_source
        init_gdk_display_source()
        from xpra.x11.bindings.core import X11CoreBindings
        from xpra.x11.bindings.window import constants, X11WindowBindings
        event_mask = constants["SubstructureNotifyMask"] | constants["SubstructureRedirectMask"]
        xwin = window.get_window().get_xid()
        X11Core = X11CoreBindings()
        root_xid = X11Core.get_root_xid()
        X11Core.UngrabPointer()
        X11Window = X11WindowBindings()
        X11Window.sendClientMessage(root_xid, xwin, False, event_mask, "_NET_WM_MOVERESIZE",
                                    int(x_root), int(y_root), int(direction), button, source_indication)

    def cancel():
        initiate(0, 0, MoveResize.CANCEL, 0, 1)

    def expand(widget):
        widget.set_hexpand(True)
        widget.set_vexpand(True)
        return widget

    grid = Gtk.Grid()
    grid.set_row_homogeneous(True)
    grid.set_column_homogeneous(True)

    btn = Gtk.Button(label="initiate move")
    grid.attach(expand(btn), 2, 2, 1, 1)

    def initiate_move(*_args):
        cancel()
        pos = get_pointer()
        source_indication = 1  # normal
        button = 1
        initiate(pos.x, pos.y, MoveResize.MOVE, button, source_indication)
        GLib.timeout_add(5 * 1000, cancel)

    btn.connect('button-press-event', initiate_move)

    def btn_callback(_btn, _event, direction: MoveResize):
        cancel()
        pos = get_pointer()
        source_indication = 1  # normal
        button = 1
        initiate(pos.x, pos.y, direction, button, source_indication)
        GLib.timeout_add(5 * 1000, cancel)

    def add_button(x: int, y: int, direction: MoveResize):
        btn = Gtk.Button(label=MOVERESIZE_DIRECTION_STRING[direction])
        btn.connect('button-press-event', btn_callback, direction)
        grid.attach(expand(btn), x, y, 1, 1)

    for x, y, direction in (
            (0, 0, MoveResize.SIZE_TOPLEFT),
            (1, 0, MoveResize.SIZE_TOP),
            (2, 0, MoveResize.SIZE_TOPRIGHT),
            (0, 1, MoveResize.SIZE_LEFT),
            (1, 1, MoveResize.MOVE),
            (2, 1, MoveResize.SIZE_RIGHT),
            (0, 2, MoveResize.SIZE_BOTTOMLEFT),
            (1, 2, MoveResize.SIZE_BOTTOM),
            (2, 2, MoveResize.SIZE_BOTTOMRIGHT),
    ):
        add_button(x, y, direction)
    grid.show_all()
    window.add(grid)
    window.set_size_request(width, height)
    return window


def main():
    from xpra.gtk.signals import quit_on_signals
    with program_context("initiate-moveresize", "Initiate Move-Resize"):
        w = make_window()
        w.show_all()
        add_close_accel(w, Gtk.main_quit)
        quit_on_signals("move resize test window")
        Gtk.main()
        return 0


if __name__ == "__main__":
    main()
