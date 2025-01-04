#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>

import sys
import warnings
from collections import deque

from xpra.util.str_fn import csv
from xpra.os_util import gi_import
from xpra.platform import program_context
from xpra.platform.gui import force_focus
from xpra.gtk.widget import label
from xpra.gtk.keymap import get_default_keymap
from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.log import enable_color, Logger

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GLib = gi_import("GLib")

log = Logger("gtk", "keyboard")


class KeyboardStateInfoWindow:

    def __init__(self):
        self.init_constants()
        self.window = Gtk.Window()
        self.window.connect("destroy", self.destroy)
        self.window.set_default_size(540, 800)
        self.window.set_position(Gtk.WindowPosition.CENTER)
        self.window.set_border_width(20)
        self.window.set_title("Keyboard State Tool")

        # Title
        vbox = Gtk.VBox(homogeneous=False, spacing=0)
        vbox.set_spacing(15)
        vbox.pack_start(label("Keyboard State", font="sans 13"))

        self.modifiers = label()
        vbox.add(self.modifiers)

        self.mouse = label()
        vbox.add(self.mouse)

        self.keys = label("", font="monospace 9")
        vbox.add(self.keys)

        self.window.add(vbox)
        GLib.timeout_add(100, self.populate_modifiers)

        self.key_events: deque[str] = deque(maxlen=35)
        self.window.connect("key-press-event", self.key_press)
        self.window.connect("key-release-event", self.key_release)
        keymap = get_default_keymap()
        self.keymap_change_timer = 0
        keymap.connect("keys-changed", self.keymap_changed)
        self.show_keymap("current keymap")

        icon = get_icon_pixbuf("keyboard.png")
        if icon:
            self.window.set_icon(icon)

    def init_constants(self) -> None:
        self.modifier_names = {
            Gdk.ModifierType.SHIFT_MASK: "Shift",
            Gdk.ModifierType.LOCK_MASK: "Lock",
            Gdk.ModifierType.CONTROL_MASK: "Control",
            Gdk.ModifierType.MOD1_MASK: "mod1",
            Gdk.ModifierType.MOD2_MASK: "mod2",
            Gdk.ModifierType.MOD3_MASK: "mod3",
            Gdk.ModifierType.MOD4_MASK: "mod4",
            Gdk.ModifierType.MOD5_MASK: "mod5"
        }
        self.short_modifier_names = {
            Gdk.ModifierType.SHIFT_MASK: "S",
            Gdk.ModifierType.LOCK_MASK: "L",
            Gdk.ModifierType.CONTROL_MASK: "C",
            Gdk.ModifierType.MOD1_MASK: "1",
            Gdk.ModifierType.MOD2_MASK: "2",
            Gdk.ModifierType.MOD3_MASK: "3",
            Gdk.ModifierType.MOD4_MASK: "4",
            Gdk.ModifierType.MOD5_MASK: "5"
        }

    def populate_modifiers(self, *_args) -> bool:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            x, y, current_mask = self.window.get_root_window().get_pointer()[-3:]
        self.mouse.set_text("%s %s" % (x, y))
        modifiers = self.mask_to_names(current_mask, self.modifier_names)
        self.modifiers.set_text(str(modifiers))
        return True

    def mask_to_names(self, mask, names_dict: dict[int, str]) -> list[str]:
        names = []
        for m, name in names_dict.items():
            if mask & m:
                names.append(name)
        return names

    def keymap_changed(self, *args) -> None:
        log.info("keymap_changed%s" % (args,))
        if not self.keymap_change_timer:
            self.keymap_change_timer = GLib.timeout_add(500, self.show_keymap)

    def show_keymap(self, msg="keymap changed:") -> None:
        self.keymap_change_timer = 0
        from xpra.platform.keyboard import Keyboard
        if not Keyboard:
            log.warn("no keyboard support!")
            return
        keyboard = Keyboard()  # pylint: disable=not-callable
        model, layout, layouts, variant, variants, options = keyboard.get_layout_spec()
        self.add_event_text(msg)
        for k, v in {
            "model": model,
            "layout": layout,
            "variant": variant,
            "layouts": layouts,
            "variants": variants,
            "options": options,
        }.items():
            if v:
                if isinstance(v, (list, tuple)):
                    v = csv(v)
                self.add_event_text("%16s: %s" % (k, v))
        log.info(f"do_keymap_changed: {msg}")
        log.info("do_keymap_changed: " + csv((layout, layouts, variant, variants, options)))

    def key_press(self, _, event) -> None:
        self.add_key_event("down", event)

    def key_release(self, _, event) -> None:
        self.add_key_event("up", event)

    def add_key_event(self, etype, event) -> None:
        modifiers = self.mask_to_names(event.state, self.short_modifier_names)
        name = Gdk.keyval_name(event.keyval)
        text = ""
        for v, l in ((etype, 5), (name, 24), (repr(event.string), 8),
                     (event.keyval, 10), (event.hardware_keycode, 10),
                     (event.is_modifier, 2), (event.group, 5),
                     (csv(modifiers), -1)):
            s = str(v)
            if l > 0:
                s = s.ljust(l)
            text += s
        self.add_event_text(text)

    def add_event_text(self, text) -> None:
        self.key_events.append(text)
        self.keys.set_text("\n".join(self.key_events))

    def destroy(self, *_args) -> None:
        Gtk.main_quit()

    def show_with_focus(self) -> None:
        force_focus()
        self.window.show_all()
        self.window.present()


def main() -> int:
    # pylint: disable=import-outside-toplevel
    from xpra.platform.gui import init, set_default_icon
    from xpra.gtk.util import init_display_source
    with program_context("Keyboard-Test", "Keyboard Test Tool"):
        enable_color()

        set_default_icon("keyboard.png")
        init()

        from xpra.gtk.signals import quit_on_signals
        quit_on_signals("keyboard test window")

        init_display_source()
        w = KeyboardStateInfoWindow()
        GLib.idle_add(w.show_with_focus)
        Gtk.main()
    return 0


if __name__ == "__main__":
    main()
    sys.exit(0)
