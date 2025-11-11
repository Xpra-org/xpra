#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from typing import Any

from xpra.gtk.window import add_close_accel
from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.gtk.widget import label, setfont
from xpra.platform.gui import force_focus
from xpra.os_util import gi_import
from xpra.exit_codes import ExitValue
from xpra.common import noop
from xpra.log import (
    Logger, CATEGORY_INFO, STRUCT_KNOWN_FILTERS,
    enable_color, enable_debug_for, disable_debug_for, debug_enabled_categories,
)

log = Logger("util")

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")


def make_category_widgets(groups: dict[str, dict[str, str]], enabled: set[str], sensitive=True,
                          toggled=noop) -> tuple[list[Any], dict[str, Any]]:
    expanders = []
    widgets = {}

    def eact(expander, *_args):
        expanded = expander.get_expanded()
        if expanded:
            return
        for exp in expanders:
            if exp != expander:
                exp.set_expanded(False)

    for group, categories in groups.items():
        exp = Gtk.Expander(label=group)
        exp.connect("activate", eact)
        setfont(exp, "sans 16")
        grid = Gtk.Grid()
        grid.set_row_homogeneous(True)
        grid.set_column_homogeneous(False)
        exp.add(grid)
        row = 0
        for category, descr in categories.items():
            cb = Gtk.CheckButton(label=category)
            setfont(cb, "courier 14")
            cb.set_active(category in enabled)
            cb.connect("toggled", toggled, category)
            cb.set_sensitive(sensitive)
            grid.attach(cb, 0, row, 1, 1)
            descr = CATEGORY_INFO.get(category, "")
            if descr:
                lbl = label(descr, font="sans 14")
                lbl.set_halign(Gtk.Align.START)
                lbl.set_margin_start(32)
                grid.attach(lbl, 1, row, 1, 1)
            row += 1
            widgets[category] = cb
        expanders.append(exp)
    return expanders, widgets


class DebugConfig:

    def __init__(self, text="Configure Client Debug Categories",
                 groups=STRUCT_KNOWN_FILTERS, enabled=debug_enabled_categories,
                 enable=enable_debug_for, disable=disable_debug_for):
        self.text = text
        self.window: Gtk.Window | None = None
        self.groups = groups
        self.enabled = enabled
        self.enable = enable
        self.disable = disable
        self.is_closed = False
        self.setup_window()

    def setup_window(self) -> None:
        self.window = Gtk.Window()
        self.window.set_border_width(20)
        self.window.connect("delete-event", self.close)
        self.window.set_default_size(400, 300)
        self.window.set_title("Xpra Debug Config")

        def window_deleted(*_args):
            self.is_closed = True
            self.hide()

        add_close_accel(self.window, window_deleted)
        self.window.connect("delete_event", window_deleted)

        icon_pixbuf = get_icon_pixbuf("bugs.png")
        if icon_pixbuf:
            self.window.set_icon(icon_pixbuf)
        self.window.set_position(Gtk.WindowPosition.CENTER)

        vbox = Gtk.VBox(homogeneous=False, spacing=0)
        vbox.set_spacing(15)

        vbox.add(label(self.text, font="Sans 16"))

        for widget in make_category_widgets(self.groups, self.enabled, True, self.category_toggled)[0]:
            vbox.pack_start(widget, True, True, 0)

        def accel_close(*_args) -> None:
            self.close()

        add_close_accel(self.window, accel_close)
        vbox.show_all()
        self.window.add(vbox)

    def category_toggled(self, btn, category: str) -> None:
        active = btn.get_active()
        log("category_toggled(%s, %s) active=%s", btn, category, active)
        if active:
            self.enable(category)
        else:
            self.disable(category)

    def show(self) -> None:
        log("show()")
        if not self.window:
            self.setup_window()
        force_focus()
        self.window.show_all()
        self.window.present()

    def hide(self) -> None:
        log("hide()")
        if self.window:
            self.window.hide()

    def close(self, *_args) -> bool:
        self.hide_window()
        return True

    def hide_window(self) -> None:
        log("hide_window()")
        if self.window:
            self.hide()
            self.window = None

    def destroy(self, *args) -> None:
        log("destroy%s", args)
        if self.window:
            self.window.destroy()
            self.window = None

    @staticmethod
    def run() -> ExitValue:
        log("run()")
        Gtk.main()
        log("run() Gtk.main done")
        return 0

    def quit(self, *args) -> None:
        log("quit%s", args)
        self.hide_window()
        Gtk.main_quit()


def main(argv=()) -> int:
    # pylint: disable=import-outside-toplevel
    from xpra.platform import program_context
    from xpra.platform.gui import init, set_default_icon
    from xpra.gtk.util import init_display_source
    with program_context("Xpra-Debug-Config", "Xpra Debug Config"):
        enable_color()
        init_display_source(False)
        set_default_icon("bugs.png")
        init()

        if "-v" in argv:
            enable_debug_for("util")

        from xpra.util.glib import register_os_signals
        app = DebugConfig("Configure Debug Categories",
                          STRUCT_KNOWN_FILTERS, debug_enabled_categories,
                          enable_debug_for, disable_debug_for)
        app.close = app.quit
        register_os_signals(app.quit, "Debug Config")
        try:
            from xpra.platform.gui import ready as gui_ready
            gui_ready()
            app.show()
            app.run()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
