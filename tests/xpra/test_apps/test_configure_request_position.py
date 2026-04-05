#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
#
# Reproducer for applications that use StaticGravity and send a post-map
# ConfigureRequest to insist on a remembered screen position.
#
# The application:
#   1. Sets WM_NORMAL_HINTS with a specific (saved) position, size, min_size,
#      and win_gravity=StaticGravity (10).
#   2. Sets _NET_WM_WINDOW_TYPE to [DIALOG, _KDEOVERRIDE, NORMAL].
#   3. Maps the window (WM places it somewhere, e.g. centred).
#   4. ~100 ms later sends a ConfigureRequest for its saved position, overriding
#      the WM's initial placement.
#
# Run under xpra to observe the ConfigureRequest handling:
#   xpra start :10 --start=python3 tests/xpra/test_apps/test_configure_request_position.py -d window

from xpra.os_util import gi_import

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")

TARGET_X, TARGET_Y = 1853, 798
WIDTH, HEIGHT = 299, 203
MIN_W, MIN_H = 100, 18
STATIC_GRAVITY = 10   # X11 StaticGravity


def main():
    window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
    window.set_title("ConfigureRequest StaticGravity reproducer")
    window.set_size_request(WIDTH, HEIGHT)
    window.set_default_size(WIDTH, HEIGHT)
    window.connect("delete_event", Gtk.main_quit)
    window.realize()

    from xpra.x11.gtk.display_source import init_gdk_display_source
    init_gdk_display_source()

    xid = window.get_window().get_xid()

    hints = {
        "position":    (TARGET_X, TARGET_Y),
        "size":        (WIDTH, HEIGHT),
        "min_size":    (MIN_W, MIN_H),
        "win_gravity": STATIC_GRAVITY,
    }

    from xpra.x11.bindings.window import X11WindowBindings
    from xpra.x11.prop import array_set

    array_set(xid, "_NET_WM_WINDOW_TYPE", "atom", [
        "_NET_WM_WINDOW_TYPE_DIALOG",
        "_NET_WM_WINDOW_TYPE__KDEOVERRIDE",
        "_NET_WM_WINDOW_TYPE_NORMAL",
    ])

    window.show_all()

    def send_configure_request():
        # GTK move+resize → XConfigureWindow → ConfigureRequest to the WM.
        # With StaticGravity the x,y are root-window coordinates, so the WM
        # should honour the saved position and move the window there.
        window.move(TARGET_X, TARGET_Y)
        window.resize(WIDTH, HEIGHT)
        return False   # one-shot

    def after_map():
        # Re-apply WM_NORMAL_HINTS: GTK overwrites them during show_all()
        # (it derives min_size from set_size_request and clears position/gravity).
        X11WindowBindings().setSizeHints(xid, hints)
        GLib.timeout_add(100, send_configure_request)
        return False   # one-shot

    GLib.idle_add(after_map)
    Gtk.main()


if __name__ == "__main__":
    main()
