#!/usr/bin/env python3
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
import os

from xpra.os_util import gi_import
from xpra.platform import program_context
from xpra.platform.gui import force_focus
from xpra.gtk.window import add_close_accel
from xpra.gtk.pixbuf import get_icon_pixbuf

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GLib = gi_import("GLib")


def make_window() -> Gtk.Window:
    window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
    window.set_title("Window States")
    window.set_size_request(320, 500)
    window.set_position(Gtk.WindowPosition.CENTER)
    window.connect("delete_event", Gtk.main_quit)
    icon = get_icon_pixbuf("ticked.png")
    if icon:
        window.set_icon(icon)
    vbox = Gtk.VBox(homogeneous=False, spacing=0)

    def add_buttons(t1, cb1, t2, cb2) -> None:
        hbox = Gtk.HBox(homogeneous=True, spacing=10)
        b1 = Gtk.Button(label=t1)

        def vcb1(*_args) -> None:
            cb1()

        b1.connect('clicked', vcb1)
        hbox.pack_start(b1, expand=True, fill=False, padding=5)
        b2 = Gtk.Button(label=t2)

        def vcb2(*_args) -> None:
            cb2()

        b2.connect('clicked', vcb2)
        hbox.pack_start(b2, expand=True, fill=False, padding=5)
        vbox.pack_start(hbox, expand=False, fill=False, padding=2)

    add_buttons("maximize", window.maximize, "unmaximize", window.unmaximize)
    # fullscreen-monitors:
    hbox = Gtk.HBox()
    fsm_entry = Gtk.Entry()
    fsm_entry.set_text("0,0,0,0")
    hbox.add(fsm_entry)

    def set_fsm(*_args) -> None:
        v = fsm_entry.get_text()
        strs = v.split(",")
        assert len(strs) == 4, "the list of monitors must have 4 items!"
        monitors = [int(x) for x in strs]
        from xpra.platform.gui import set_fullscreen_monitors
        set_fullscreen_monitors(window.get_window(), monitors)

    set_fsm_btn = Gtk.Button(label="Set Fullscreen Monitors")
    set_fsm_btn.connect("clicked", set_fsm)
    hbox.add(set_fsm_btn)
    vbox.pack_start(hbox, expand=False, fill=False, padding=2)
    add_buttons("fullscreen", window.fullscreen, "unfullscreen", window.unfullscreen)

    def decorate() -> None:
        window.set_decorated(True)

    def undecorate() -> None:
        window.set_decorated(False)

    add_buttons("decorate", decorate, "undecorate", undecorate)
    add_buttons("iconify", window.iconify, "deiconify", window.deiconify)

    def above() -> None:
        window.set_keep_above(True)

    def notabove() -> None:
        window.set_keep_above(False)

    add_buttons("keep above", above, "not above", notabove)

    def below() -> None:
        window.set_keep_below(True)

    def notbelow() -> None:
        window.set_keep_below(False)

    add_buttons("keep below", below, "not below", notbelow)
    add_buttons("stick", window.stick, "unstick", window.unstick)

    def skip_pager() -> None:
        window.set_skip_pager_hint(True)

    def notskip_pager() -> None:
        window.set_skip_pager_hint(False)

    add_buttons("skip pager", skip_pager, "not skip pager", notskip_pager)

    def skip_taskbar() -> None:
        window.set_skip_taskbar_hint(True)

    def notskip_taskbar() -> None:
        window.set_skip_taskbar_hint(False)

    add_buttons("skip taskbar", skip_taskbar, "not skip taskbar", notskip_taskbar)

    def may_need_x11() -> None:
        from xpra.util.system import is_X11
        if is_X11() and not os.environ.get("X11_DISPLAY_SOURCE"):
            os.environ["X11_DISPLAY_SOURCE"] = "1"
            try:
                from xpra.x11.bindings.posix_display_source import init_posix_display_source  # @UnresolvedImport
                init_posix_display_source()
            except ImportError:
                pass

    def shade() -> None:
        may_need_x11()
        from xpra.platform.gui import set_shaded
        set_shaded(window.get_window(), True)

    def unshade() -> None:
        may_need_x11()
        from xpra.platform.gui import set_shaded
        set_shaded(window.get_window(), False)

    add_buttons("shade", shade, "unshade", unshade)

    def modal() -> None:
        window.set_modal(True)

    def notmodal() -> None:
        window.set_modal(False)

    add_buttons("modal", modal, "not modal", notmodal)

    def window_state(_widget, event) -> None:
        STATES = {
            Gdk.WindowState.WITHDRAWN: "withdrawn",
            Gdk.WindowState.ICONIFIED: "iconified",
            Gdk.WindowState.MAXIMIZED: "maximized",
            Gdk.WindowState.STICKY: "sticky",
            Gdk.WindowState.FULLSCREEN: "fullscreen",
            Gdk.WindowState.ABOVE: "above",
            Gdk.WindowState.BELOW: "below",
        }
        # print("window_state(%s, %s)" % (widget, event))
        print("flags: %s" % [STATES[x] for x in STATES.keys() if x & event.new_window_state])

    window.connect("window-state-event", window_state)
    window.add(vbox)
    return window


def main() -> int:
    with program_context("window-states", "Window States"):
        w = make_window()
        add_close_accel(w, Gtk.main_quit)
        from xpra.gtk.signals import quit_on_signals
        quit_on_signals("window states test")

        def show_with_focus() -> None:
            force_focus()
            w.show_all()
            w.present()

        GLib.idle_add(show_with_focus)
        Gtk.main()
        return 0


if __name__ == "__main__":
    main()
