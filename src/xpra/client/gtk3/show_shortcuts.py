# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Pango

from xpra.os_util import SIGNAMES
from xpra.gtk_common.gtk_util import add_close_accel, get_icon_pixbuf
from xpra.gtk_common.gobject_compat import install_signal_handlers
from xpra.client.gtk_base.css_overrides import inject_css_overrides
from xpra.log import Logger

log = Logger("client", "util")

inject_css_overrides()

def lal(s, font=None):
    al = Gtk.Alignment(xalign=0, yalign=0.5, xscale=0.0, yscale=0.0)
    l = Gtk.Label(label=s)
    if font:
        l.modify_font(font)
    al.add(l)
    return al


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
        label = lal("Help: shortcuts", Pango.FontDescription("sans 18"))
        vbox.pack_start(label, True, True, 10)
        label = lal("Prefix: %s" % ("+".join(shortcut_modifiers)))
        vbox.pack_start(label, True, True, 0)
        #each key may have multiple shortcuts, count them all:
        total = 0
        for keyname in shortcuts:
            total += len(shortcuts[keyname])
        label = lal("%i Shortcuts:" % (total, ), Pango.FontDescription("sans 16"))
        vbox.pack_start(label, True, True, 20)
        table = Gtk.Table(n_rows=total+1, n_columns=2, homogeneous=True)
        row = 0
        def attach(s, x=0, font=None):
            al = Gtk.Alignment(xalign=0, yalign=0.5, xscale=0.0, yscale=0.0)
            l = Gtk.Label(label=s)
            if font:
                l.modify_font(font)
            al.add(l)
            table.attach(al, x, x+1, row, row+1,
                         xoptions=Gtk.AttachOptions.FILL, yoptions=Gtk.AttachOptions.FILL,
                         xpadding=10, ypadding=0)
        attach("Keys", 0, Pango.FontDescription("sans bold 12"))
        attach("Action", 1, Pango.FontDescription("sans bold 12"))
        row += 1
        for keyname in sorted(shortcuts.keys()):
            key_shortcuts = shortcuts[keyname]
            for shortcut in key_shortcuts:
                modifiers, action, args = shortcut
                if args:
                    action += "(%s)" % args
                keys = "+".join(list(modifiers)+[keyname])
                attach(keys, 0)
                attach(action, 1)
                row += 1
        vbox.pack_start(table, False, True, 0)
        vbox.set_margin_top(20)
        vbox.set_margin_bottom(20)
        vbox.set_margin_left(20)
        vbox.set_margin_right(20)
        self.add(vbox)


def main(_args):
    from xpra.os_util import POSIX, OSX
    from xpra.platform import program_context
    from xpra.platform.gui import force_focus
    from xpra.platform.keyboard import Keyboard
    from xpra.client.keyboard_shortcuts_parser import parse_shortcut_modifiers, parse_shortcuts, get_modifier_names
    from xpra.scripts.config import read_xpra_defaults
    with program_context("Keyboard-Shortcuts", "Keyboard Shortcuts"):
        if POSIX and not OSX:
            try:
                from xpra.x11.bindings.posix_display_source import init_posix_display_source    #@UnresolvedImport
                init_posix_display_source()
            except Exception as e:
                print("failed to connect to the X11 server:")
                print(" %s" % e)
                #hope for the best..

        keyboard = Keyboard()  #pylint: disable=not-callable
        mod_meanings = keyboard.get_keymap_modifiers()[0]
        modifier_names = get_modifier_names(mod_meanings)

        conf = read_xpra_defaults()
        key_shortcuts = conf["key-shortcut"]
        shortcut_modifiers = conf["shortcut-modifiers"]
        modifiers = parse_shortcut_modifiers(shortcut_modifiers, modifier_names)
        shortcuts = parse_shortcuts(key_shortcuts, modifiers, modifier_names=modifier_names)

        w = ShortcutInfo(modifiers, shortcuts)
        w.connect('delete_event', Gtk.main_quit)
        def handle_signal(signum, frame=None):
            log("handle_signal(%s, %s)", SIGNAMES.get(signum, signum), frame)
            GLib.idle_add(Gtk.main_quit)
        install_signal_handlers("Keyboard-Shortcuts", handle_signal)
        add_close_accel(w, Gtk.main_quit)
        force_focus()
        w.show_all()
        Gtk.main()


if __name__ == "__main__":  # pragma: no cover
    main(sys.argv)
