#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>

import sys

from xpra.os_util import gi_import
from xpra.platform import program_context
from xpra.platform.gui import force_focus
from xpra.gtk.window import add_close_accel
from xpra.gtk.widget import label
from xpra.gtk.pixbuf import get_icon_pixbuf

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GLib = gi_import("GLib")
GObject = gi_import("GObject")


class TestForm:

    def __init__(self):
        self.window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.window.connect("destroy", Gtk.main_quit)
        self.window.set_title("Test Button Events")
        self.window.set_default_size(320, 200)
        self.window.set_border_width(20)
        self.window.set_position(Gtk.WindowPosition.CENTER)
        icon = get_icon_pixbuf("pointer.png")
        if icon:
            self.window.set_icon(icon)

        vbox = Gtk.VBox()
        self.info = label("")
        self.show_click_settings()
        GLib.timeout_add(1000, self.show_click_settings)
        vbox.pack_start(self.info, False, False, 0)
        self.event_label = label("Ready")
        vbox.pack_start(self.event_label, False, False, 0)

        self.eventbox = Gtk.EventBox()
        self.eventbox.connect('button-press-event', self.button_press_event)
        self.eventbox.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.eventbox.add_events(Gdk.EventMask.BUTTON_RELEASE_MASK)
        vbox.pack_start(self.eventbox, True, True, 0)
        self.window.add(vbox)

    def show_with_focus(self) -> None:
        force_focus()
        self.window.show_all()
        self.window.present()

    def show_click_settings(self) -> bool:
        root = Gdk.get_default_root_window()
        screen = root.get_screen()
        # use undocumented constants found in source:
        t = ""
        try:
            val = GObject.Value()
            val.init(GObject.TYPE_INT)
            if screen.get_setting("gtk-double-click-time"):
                t = val.get_int()
        except Exception:
            t = ""
        d = ""
        try:
            val = GObject.Value()
            val.init(GObject.TYPE_INT)
            if screen.get_setting("gtk-double-click-distance"):
                d = val.get_int()
        except Exception:
            d = ""
        self.info.set_text(f"Time (ms): {t}, Distance: {d}")
        return True

    def button_press_event(self, _obj, event) -> None:
        # nothing we can do about the "_" prefixed names that Gdk uses
        # noinspection PyProtectedMember
        if event.type == Gdk.EventType._3BUTTON_PRESS:  # pylint: disable=protected-access
            self.event_label.set_text("Triple Click!")
        elif event.type == Gdk.EventType._2BUTTON_PRESS:  # pylint: disable=protected-access
            self.event_label.set_text("Double Click!")
        elif event.type == Gdk.EventType.BUTTON_PRESS:
            self.event_label.set_text("Click")
        else:
            self.event_label.set_text("Unexpected event: %s" % event)


def main() -> None:
    from xpra.gtk.util import quit_on_signals
    with program_context("clicks", "Clicks"):
        w = TestForm()
        add_close_accel(w.window, Gtk.main_quit)
        GLib.idle_add(w.show_with_focus)
        quit_on_signals("clicks test window")
        Gtk.main()


if __name__ == "__main__":
    main()
    sys.exit(0)
