#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import signal
from collections.abc import Callable

from xpra.gtk.window import add_close_accel
from xpra.gtk.widget import scaled_image, label
from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.util.glib import register_os_signals
from xpra.util.objects import typedict
from xpra.util.config import parse_user_config_file, update_config_attribute
from xpra.exit_codes import ExitValue
from xpra.common import noop
from xpra.os_util import gi_import
from xpra.log import Logger, enable_debug_for

Gtk = gi_import("Gtk")

log = Logger("exec")

START_NEW_COMMAND_CONFIG = "start_new_command.conf"


def update_config(prop: str, value: str) -> None:
    update_config_attribute(prop, value, dirname="tools", filename=START_NEW_COMMAND_CONFIG)


def load_config() -> dict:
    return parse_user_config_file("tools", START_NEW_COMMAND_CONFIG)


def btn(label, tooltip, callback, icon_name="") -> Gtk.Button:
    b = Gtk.Button(label=label)
    b.set_tooltip_text(tooltip)
    b.connect("clicked", callback)
    icon = get_icon_pixbuf(icon_name)
    if icon:
        b.set_image(scaled_image(icon, 24))
    return b


class StartNewCommand:

    def __init__(self, run_callback: Callable = noop, can_share=False, menu=None):
        self.run_callback = run_callback
        self.menu = typedict(menu or {})
        self.window = Gtk.Window()
        self.window.set_border_width(20)
        self.window.connect("delete-event", self.close)
        self.window.set_default_size(400, 150)
        self.window.set_title("Start New Command")

        self.prefs = load_config()

        icon_pixbuf = get_icon_pixbuf("forward.png")
        if icon_pixbuf:
            self.window.set_icon(icon_pixbuf)
        self.window.set_position(Gtk.WindowPosition.CENTER)

        vbox = Gtk.VBox(homogeneous=False, spacing=0)
        vbox.set_spacing(0)

        self.entry = Gtk.Entry()
        self.entry.set_max_length(255)
        self.entry.set_width_chars(32)
        self.entry.connect('activate', self.run_command)
        if self.menu:
            # or use menus if we have xdg data:
            hbox = Gtk.HBox(homogeneous=False, spacing=20)
            vbox.add(hbox)
            hbox.add(label("Category:"))
            self.category_combo = Gtk.ComboBoxText()
            hbox.add(self.category_combo)
            index = 0
            for i, name in enumerate(sorted(self.menu.keys())):
                self.category_combo.append_text(name)
                if name == self.prefs.get("category", ""):
                    index = i
            self.category_combo.set_active(index)
            self.category_combo.connect("changed", self.category_changed)

            hbox = Gtk.HBox(homogeneous=False, spacing=20)
            vbox.add(hbox)
            self.command_combo = Gtk.ComboBoxText()
            hbox.pack_start(label("Command:"))
            hbox.pack_start(self.command_combo)
            self.command_combo.connect("changed", self.command_changed)
            # this will populate the command combo:
            self.category_changed()
        # always show the command as text so that it can be edited:
        entry_label = label("Command to run:", font="sans 14")
        entry_al = Gtk.Alignment(xalign=0, yalign=0.5, xscale=0.0, yscale=0)
        entry_al.add(entry_label)
        vbox.add(entry_al)
        # Actual command:
        vbox.add(self.entry)

        if can_share:
            self.share = Gtk.CheckButton(label="Shared", use_underline=False)
            # shared commands will also be shown to other clients
            self.share.set_active(True)
            vbox.add(self.share)
        else:
            self.share = None

        # Buttons:
        hbox = Gtk.HBox(homogeneous=False, spacing=20)
        vbox.pack_start(hbox)
        hbox.pack_start(btn("Run", "Run this command", self.run_command, "forward.png"))
        hbox.pack_start(btn("Cancel", "", self.close, "quit.png"))

        def accel_close(*_args) -> None:
            self.close()

        add_close_accel(self.window, accel_close)
        vbox.show_all()
        self.window.vbox = vbox
        self.window.add(vbox)

    def category_changed(self, *args) -> None:
        category = self.category_combo.get_active_text()
        update_config("category", category)
        entries = typedict(typedict(self.menu.dictget(category, {})).dictget("Entries", {}))
        log("category_changed(%s) category=%s, entries=%s", args, category, entries)
        self.command_combo.get_model().clear()
        index = -1
        for i, name in enumerate(entries.keys()):
            self.command_combo.append_text(name)
            if name == self.prefs.get("command", ""):
                index = i
        if index >= 0:
            self.command_combo.set_active(index)

    def command_changed(self, *args) -> None:
        if not self.entry:
            return
        category = self.category_combo.get_active_text()
        entries = typedict(typedict(self.menu.dictget(category, {})).dictget("Entries", {}))
        command_name = self.command_combo.get_active_text()
        if command_name:
            update_config("command", command_name)
        log("command_changed(%s) category=%s, entries=%s, command_name=%s", args, category, entries, command_name)
        command = ""
        if entries and command_name:
            command_props = typedict(typedict(entries).dictget(command_name, {}))
            log("command properties=%s", command_props)
            command = typedict(command_props).strget("command")
        self.entry.set_text(command)

    def show(self) -> None:
        log("show()")
        self.window.show()
        self.window.present()

    def hide(self) -> None:
        log("hide()")
        if self.window:
            self.window.hide()

    def close(self, *args) -> bool:
        log("close%s", args)
        self.hide()
        return True

    def destroy(self, *args) -> None:
        log("close%s", args)
        if self.window:
            self.window.destroy()
            self.window = None

    def run(self) -> ExitValue:
        log("run()")
        Gtk.main()
        log("run() Gtk.main done")
        return 0

    def quit(self, *args) -> None:
        log("quit%s", args)
        self.close()
        Gtk.main_quit()

    def run_command(self, *_args) -> None:
        self.hide()
        command = self.entry.get_text()
        log("command=%s", command)
        if self.run_callback and command:
            self.run_callback(command, self.share is None or self.share.get_active())


_instance: StartNewCommand | None = None


def get_start_new_command_gui(run_callback: Callable = noop, can_share=False, menu=None) -> StartNewCommand:
    global _instance
    if _instance is None:
        _instance = StartNewCommand(run_callback, can_share, menu)
    return _instance


def main() -> int:  # pragma: no cover
    from xpra.platform.gui import init as gui_init, ready as gui_ready
    from xpra.platform import program_context
    gui_init()
    with program_context("Start-New-Command", "Start New Command"):
        if "-v" in sys.argv:
            enable_debug_for("util")

        app = StartNewCommand()
        app.hide = app.quit
        register_os_signals(app.quit)
        try:
            gui_ready()
            app.show()
            return app.run()
        except KeyboardInterrupt:
            return 128 + int(signal.SIGINT)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
