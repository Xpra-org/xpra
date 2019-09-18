#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2019 Antoine Martin <antoine@xpra.org>

import sys
from collections import deque
from gi.repository import GLib, Pango, Gtk, Gdk

from xpra.platform.paths import get_icon


class KeyboardStateInfoWindow:

    def    __init__(self):
        self.init_constants()
        self.window = Gtk.Window()
        self.window.connect("destroy", self.destroy)
        self.window.set_default_size(540, 800)
        self.window.set_border_width(20)
        self.window.set_title("Keyboard State Tool")

        # Title
        vbox = Gtk.VBox(False, 0)
        vbox.set_spacing(15)
        label = Gtk.Label("Keyboard State")
        label.modify_font(Pango.FontDescription("sans 13"))
        vbox.pack_start(label)

        self.modifiers = Gtk.Label()
        vbox.add(self.modifiers)

        self.mouse = Gtk.Label()
        vbox.add(self.mouse)

        self.keys = Gtk.Label()
        fixed = Pango.FontDescription('monospace 9')
        self.keys.modify_font(fixed)
        vbox.add(self.keys)

        self.window.add(vbox)
        self.window.show_all()
        GLib.timeout_add(100, self.populate_modifiers)

        self.key_events = deque(maxlen=35)
        self.window.connect("key-press-event", self.key_press)
        self.window.connect("key-release-event", self.key_release)

        icon = get_icon("keyboard.png")
        if icon:
            self.window.set_icon(icon)

    def init_constants(self):
        self.modifier_names = {
            Gdk.ModifierType.SHIFT_MASK        : "Shift",
            Gdk.ModifierType.LOCK_MASK         : "Lock",
            Gdk.ModifierType.CONTROL_MASK      : "Control",
            Gdk.ModifierType.MOD1_MASK         : "mod1",
            Gdk.ModifierType.MOD2_MASK         : "mod2",
            Gdk.ModifierType.MOD3_MASK         : "mod3",
            Gdk.ModifierType.MOD4_MASK         : "mod4",
            Gdk.ModifierType.MOD5_MASK         : "mod5"
        }
        self.short_modifier_names = {
            Gdk.ModifierType.SHIFT_MASK        : "S",
            Gdk.ModifierType.LOCK_MASK         : "L",
            Gdk.ModifierType.CONTROL_MASK      : "C",
            Gdk.ModifierType.MOD1_MASK         : "1",
            Gdk.ModifierType.MOD2_MASK         : "2",
            Gdk.ModifierType.MOD3_MASK         : "3",
            Gdk.ModifierType.MOD4_MASK         : "4",
            Gdk.ModifierType.MOD5_MASK         : "5"
        }

    def populate_modifiers(self, *_args):
        (x, y, current_mask) = self.window.get_root_window().get_pointer()[-3:]
        self.mouse.set_text("%s %s" % (x, y))
        modifiers = self.mask_to_names(current_mask, self.modifier_names)
        self.modifiers.set_text(str(modifiers))
        return    True

    def mask_to_names(self, mask, names_dict):
        names = []
        for m,name in names_dict.items():
            if mask & m:
                names.append(name)
        return  names

    def key_press(self, _, event):
        self.add_key_event("down", event)

    def key_release(self, _, event):
        self.add_key_event("up", event)

    def add_key_event(self, etype, event):
        modifiers = self.mask_to_names(event.state, self.short_modifier_names)
        name = Gdk.keyval_name(event.keyval)
        text = ""
        for v,l in ((etype, 5), (name, 24), (event.string, 4),
                    (event.keyval, 10), (event.hardware_keycode, 10),
                    (event.is_modifier, 2), (event.group, 2),
                    (modifiers, -1)):
            s = str(v).replace("\n", "\\n").replace("\r", "\\r")
            if l>0:
                s = s.ljust(l)
            text += s
        self.key_events.append(text)
        self.keys.set_text("\n".join(self.key_events))

    def destroy(self, *_args):
        Gtk.main_quit()


def main():
    from xpra.platform import program_context
    from xpra.log import enable_color
    with program_context("Keyboard-Test", "Keyboard Test Tool"):
        enable_color()
        KeyboardStateInfoWindow()
        Gtk.main()


if __name__ == "__main__":
    main()
    sys.exit(0)
