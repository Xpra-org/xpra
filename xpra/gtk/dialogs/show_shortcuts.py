# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from xpra.os_util import gi_import
from xpra.util.str_fn import sorted_nicely
from xpra.gtk.window import add_close_accel
from xpra.gtk.widget import label
from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.gtk.signals import quit_on_signals
from xpra.gtk.css_overrides import inject_css_overrides
from xpra.log import Logger

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")

log = Logger("client", "util")

inject_css_overrides()


def lal(text: str, font="") -> Gtk.Alignment:
    align = Gtk.Alignment(xalign=0, yalign=0.5, xscale=0.0, yscale=0.0)
    lbl = label(text, font=font)
    align.add(lbl)
    return align


class ShortcutInfo(Gtk.Window):

    def __init__(self, shortcut_modifiers=(), shortcuts=()):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)

        def window_deleted(*_args):
            self.is_closed = True

        self.connect('delete_event', window_deleted)
        self.set_title("Xpra Keyboard Shortcuts")
        self.set_size_request(320, 320)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.is_closed = False
        vbox = Gtk.VBox()
        vbox.set_spacing(10)
        icon = get_icon_pixbuf("keyboard.png")
        if icon:
            self.set_icon(icon)

        def vlabel(text, font="", padding=0):
            vbox.pack_start(lal(text, font), True, True, padding)

        vlabel("Help: shortcuts", "sans 18", 10)
        vlabel("Prefix: %s" % ("+".join(shortcut_modifiers)), padding=0)
        # each key may have multiple shortcuts, count them all:
        total = 0
        for keyname in shortcuts:
            total += len(shortcuts[keyname])
        vlabel("%i Shortcuts:" % (total,), "sans 16", 20)

        grid = Gtk.Grid()
        grid.set_row_homogeneous(True)
        grid.set_column_homogeneous(True)

        row = 0

        def attach(s: str, x=0, font="") -> None:
            align = Gtk.Alignment(xalign=0, yalign=0.5, xscale=0.0, yscale=0.0)
            lbl = label(s, font=font)
            lbl.set_margin_start(5)
            lbl.set_margin_top(2)
            lbl.set_margin_end(5)
            lbl.set_margin_bottom(2)
            align.add(lbl)
            grid.attach(align, x, row, 1, 1)

        attach("Keys", 0, "sans bold 12")
        attach("Action", 1, "sans bold 12")
        row += 1
        for keyname in sorted_nicely(shortcuts.keys()):
            key_shortcuts = shortcuts[keyname]
            for shortcut in key_shortcuts:
                modifiers, action, args = shortcut
                if args:
                    action += "(%s)" % args
                keys = "+".join(list(modifiers) + [keyname])
                attach(keys, 0)
                attach(action, 1)
                row += 1
        vbox.pack_start(grid, False, True, 0)
        vbox.set_margin_top(20)
        vbox.set_margin_bottom(20)
        vbox.set_margin_start(20)
        vbox.set_margin_end(20)
        self.add(vbox)


def main(_args):
    from xpra.os_util import POSIX, OSX
    from xpra.platform import program_context
    from xpra.platform.gui import force_focus
    from xpra.platform.keyboard import Keyboard
    from xpra.client.gui.keyboard_shortcuts_parser import parse_shortcut_modifiers, parse_shortcuts, get_modifier_names
    from xpra.scripts.config import read_xpra_defaults
    with program_context("Keyboard-Shortcuts", "Keyboard Shortcuts"):
        if POSIX and not OSX:
            try:
                from xpra.x11.bindings.posix_display_source import init_posix_display_source
                init_posix_display_source()
            except Exception as e:
                log("init_posix_display_source failure", exc_info=True)
                log.warn("Warning: failed to connect to the X11 server")
                log.warn(f" {e}")
                # hope for the best..

        if not Keyboard:
            log.warn("missing keyboard support")
            return
        keyboard = Keyboard()  # pylint: disable=not-callable
        mod_meanings = keyboard.get_keymap_modifiers()[0]
        modifier_names = get_modifier_names(mod_meanings)

        conf = read_xpra_defaults()
        key_shortcuts = conf["key-shortcut"]
        shortcut_modifiers = conf["shortcut-modifiers"]
        modifiers = parse_shortcut_modifiers(shortcut_modifiers, modifier_names)
        shortcuts = parse_shortcuts(key_shortcuts, modifiers, modifier_names=modifier_names)

        w = ShortcutInfo(modifiers, shortcuts)
        w.connect('delete_event', Gtk.main_quit)

        quit_on_signals("Keyboard-Shortcuts")
        add_close_accel(w, Gtk.main_quit)
        force_focus()
        w.show_all()
        Gtk.main()


if __name__ == "__main__":  # pragma: no cover
    main(sys.argv)
