#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011-2023 Antoine Martin <antoine@xpra.org>

import sys
from collections import deque
import gi

from xpra.util import csv
from xpra.os_util import bytestostr
from xpra.platform import program_context
from xpra.platform.gui import force_focus
from xpra.gtk_common.gtk_util import get_icon_pixbuf
from xpra.log import enable_color, Logger

gi.require_version("Gdk", "3.0")  # @UndefinedVariable
gi.require_version("Gtk", "3.0")  # @UndefinedVariable
gi.require_version("Pango", "1.0")  # @UndefinedVariable
from gi.repository import GLib, Pango, Gtk, Gdk  # @UnresolvedImport

log = Logger("gtk", "keyboard")


class KeyboardStateInfoWindow:

    def    __init__(self):
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
        label = Gtk.Label(label="Keyboard State")
        label.modify_font(Pango.FontDescription("sans 13"))
        #patch pack_start:
        from xpra.gtk_common.gtk_util import pack_start
        assert callable(pack_start)
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
        GLib.timeout_add(100, self.populate_modifiers)

        self.key_events : deque[str] = deque(maxlen=35)
        self.window.connect("key-press-event", self.key_press)
        self.window.connect("key-release-event", self.key_release)
        display = Gdk.Display.get_default()
        keymap = Gdk.Keymap.get_for_display(display)
        self.keymap_change_timer = 0
        keymap.connect("keys-changed", self.keymap_changed)
        self.show_keymap("current keymap")

        icon = get_icon_pixbuf("keyboard.png")
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

    def keymap_changed(self, *args):
        log.info("keymap_changed%s" % (args,))
        if not self.keymap_change_timer:
            self.keymap_change_timer = GLib.timeout_add(500, self.show_keymap)

    def show_keymap(self, msg="keymap changed:"):
        self.keymap_change_timer = 0
        from xpra.platform.keyboard import Keyboard
        if not Keyboard:
            log.warn("no keyboard support!")
            return
        keyboard = Keyboard()      #pylint: disable=not-callable
        layout, layouts, variant, variants, options = keyboard.get_layout_spec()
        self.add_event_text(msg)
        for k,v in {
            "layout"    : layout,
            "variant"   : variant,
            "layouts"   : layouts,
            "variants"  : variants,
            "options"  : options,
            }.items():
            if v:
                if isinstance(v, (list, tuple)):
                    v = csv(bytestostr(x) for x in v)
                self.add_event_text("%16s: %s" % (k, bytestostr(v)))
        log.info(f"do_keymap_changed: {msg}")
        log.info("do_keymap_changed: " + csv((layout, layouts, variant, variants, options)))

    def key_press(self, _, event):
        self.add_key_event("down", event)

    def key_release(self, _, event):
        self.add_key_event("up", event)

    def add_key_event(self, etype, event):
        modifiers = self.mask_to_names(event.state, self.short_modifier_names)
        name = Gdk.keyval_name(event.keyval)
        text = ""
        for v,l in ((etype, 5), (name, 24), (repr(event.string), 8),
                    (event.keyval, 10), (event.hardware_keycode, 10),
                    (event.is_modifier, 2), (event.group, 5),
                    (csv(modifiers), -1)):
            s = str(v)
            if l>0:
                s = s.ljust(l)
            text += s
        self.add_event_text(text)

    def add_event_text(self, text):
        self.key_events.append(text)
        self.keys.set_text("\n".join(self.key_events))

    def destroy(self, *_args):
        Gtk.main_quit()

    def show_with_focus(self):
        force_focus()
        self.window.show_all()
        self.window.present()


def main():
    # pylint: disable=import-outside-toplevel
    from xpra.platform.gui import init, set_default_icon
    from xpra.gtk_common.gtk_util import init_display_source
    with program_context("Keyboard-Test", "Keyboard Test Tool"):
        enable_color()

        set_default_icon("keyboard.png")
        init()

        from xpra.gtk_common.gobject_compat import register_os_signals
        def signal_handler(*_args):
            GLib.idle_add(Gtk.main_quit)
        register_os_signals(signal_handler, "test window")

        init_display_source()
        w = KeyboardStateInfoWindow()
        GLib.idle_add(w.show_with_focus)
        Gtk.main()
    return 0


if __name__ == "__main__":
    main()
    sys.exit(0)
