#!/usr/bin/env python3
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import gi_import
from xpra.platform import program_context
from xpra.platform.gui import force_focus
from xpra.gtk.util import GRAB_STATUS_STRING, quit_on_signals
from xpra.gtk.window import add_close_accel
from xpra.gtk.widget import label
from xpra.gtk.pixbuf import get_icon_pixbuf

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GLib = gi_import("GLib")


def make_grab_window() -> Gtk.Window:
    window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
    window.set_size_request(600, 200)
    window.set_title("Grabs")
    window.connect("delete_event", Gtk.main_quit)
    window.add_events(Gdk.EventMask.ALL_EVENTS_MASK)
    window.set_position(Gtk.WindowPosition.CENTER)
    icon = get_icon_pixbuf("pointer.png")
    if icon:
        window.set_icon(icon)
    vbox = Gtk.VBox(homogeneous=False, spacing=0)
    hbox = Gtk.HBox(homogeneous=False, spacing=0)
    vbox.pack_start(hbox, expand=False, fill=False, padding=10)

    def keyevent_info(event) -> str:
        keyval = event.keyval
        keycode = event.hardware_keycode
        keyname = Gdk.keyval_name(keyval)
        return "%i:%s" % (keycode, keyname)

    def key_pressed(_window, event) -> None:
        event_label.set_text("key_pressed: %s" % keyevent_info(event))

    window.connect("key-press-event", key_pressed)

    def key_released(_window, event) -> None:
        event_label.set_text("key_released: %s" % keyevent_info(event))

    window.connect("key-press-event", key_pressed)
    window.connect("key-release-event", key_released)

    def motion_notify(_window, event) -> None:
        event_label.set_text("motion: %i,%i" % (event.x_root, event.y_root))

    window.connect("motion-notify-event", motion_notify)

    grab_pointer_btn = Gtk.Button(label="grab pointer")

    def grab_pointer(*args) -> None:
        action_label.set_text("grab_pointer%s" % str(args))

        def do_grab() -> None:
            event_mask = Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
            v = Gdk.pointer_grab(window.get_window(), False, event_mask, None, None, 0)
            # Gdk.BUTTON_PRESS_MASK | Gdk.BUTTON_RELEASE_MASK | Gdk.KEY_PRESS_MASK \
            # Gdk.KEY_RELEASE_MASK | Gdk.ENTER_NOTIFY_MASK)
            # | Gdk.ENTER_NOTIFY_MASK
            # Gdk.ALL_EVENTS_MASK
            action_label.set_text("pointer_grab() returned %s" % GRAB_STATUS_STRING.get(v, v))
            GLib.timeout_add(10 * 1000, Gdk.pointer_ungrab, 0)

        print("will grab in 5 seconds!")
        GLib.timeout_add(5 * 1000, do_grab)

    grab_pointer_btn.connect('clicked', grab_pointer)
    hbox.pack_start(grab_pointer_btn, expand=False, fill=False, padding=10)

    ungrab_pointer_btn = Gtk.Button(label="ungrab pointer")

    def ungrab_pointer(*_args) -> None:
        v = Gdk.pointer_ungrab(0)
        action_label.set_text("pointer_ungrab(0)=%s" % GRAB_STATUS_STRING.get(v, v))
        window.unmaximize()

    ungrab_pointer_btn.connect('clicked', ungrab_pointer)
    hbox.pack_start(ungrab_pointer_btn, expand=False, fill=False, padding=10)

    grab_keyboard_btn = Gtk.Button(label="grab keyboard")

    def grab_keyboard(*_args) -> None:
        v = Gdk.keyboard_grab(window.get_window(), True, 0)
        action_label.set_text("keyboard_grab(..)=%s" % GRAB_STATUS_STRING.get(v, v))
        GLib.timeout_add(10 * 1000, Gdk.keyboard_ungrab, 0)

    grab_keyboard_btn.connect('clicked', grab_keyboard)
    hbox.pack_start(grab_keyboard_btn, expand=False, fill=False, padding=10)

    ungrab_keyboard_btn = Gtk.Button(label="ungrab keyboard")

    def ungrab_keyboard(*_args) -> None:
        v = Gdk.keyboard_ungrab(0)
        action_label.set_text("keyboard_ungrab(0)=%s" % GRAB_STATUS_STRING.get(v, v))

    ungrab_keyboard_btn.connect('clicked', ungrab_keyboard)
    hbox.pack_start(ungrab_keyboard_btn, expand=False, fill=False, padding=10)

    vbox.add(label("Last action:"))
    action_label = label("")
    vbox.add(action_label)

    vbox.add(label("Last event:"))
    event_label = label("")
    vbox.add(event_label)

    window.add(vbox)
    return window


def main() -> int:
    with program_context("grabs", "Grabs"):
        w = make_grab_window()

        def show_with_focus() -> None:
            force_focus()
            w.show_all()
            w.present()

        add_close_accel(w, Gtk.main_quit)
        quit_on_signals("grabs test window")
        GLib.idle_add(show_with_focus)
        Gtk.main()
        return 0


if __name__ == "__main__":
    main()
