#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from xpra.os_util import gi_import
from xpra.util.io import get_util_logger
from xpra.gtk.signals import register_os_signals
from xpra.gtk.window import add_close_accel
from xpra.gtk.widget import label
from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.platform.gui import force_focus

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")
GdkPixbuf = gi_import("GdkPixbuf")

log = get_util_logger()


class PasswordInputDialogWindow(Gtk.Dialog):

    def __init__(self, title="Title", prompt="", icon=""):
        super().__init__()
        self.set_border_width(20)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("delete-event", self.quit)
        self.set_default_size(400, 150)
        self.set_title(title)
        add_close_accel(self, self.cancel)
        self.password = ""

        icon_pixbuf = get_icon_pixbuf(icon)
        if icon_pixbuf:
            self.set_icon(icon_pixbuf)

        vbox = self.get_content_area()
        vbox.set_spacing(10)

        def al(text: str, font="sans 14", xalign=0) -> None:
            lbl = label(text, font=font)
            align = Gtk.Alignment(xalign=xalign, yalign=0.5, xscale=0.0, yscale=0)
            align.add(lbl)
            vbox.add(align)
            align.show_all()

        # window title is visible so this would be redundant:
        # al(title, "sans 18", 0.5)
        al(prompt, "sans 14")
        self.password_input = Gtk.Entry()
        self.password_input.set_max_length(255)
        self.password_input.set_width_chars(32)
        self.password_input.connect('activate', self.password_activate)
        self.password_input.connect('changed', self.password_changed)
        self.password_input.set_visibility(False)
        vbox.add(self.password_input)

        self.confirm_btn = self.add_button("Confirm", 0)
        self.set_default(self.confirm_btn)
        self.set_focus(self.confirm_btn)
        self.cancel_btn = self.add_button("Cancel", 1)

    def show(self) -> None:
        log("PasswordInputDialogWindow.show()")
        self.show_all()

        def show() -> None:
            force_focus()
            self.present()
            self.password_input.grab_focus()

        GLib.idle_add(show)

    def run(self) -> str:
        r = super().run()
        if r == 0:
            return self.get_password()
        return ""

    def quit(self, *args) -> bool:
        log("quit%s", args)
        self.destroy()
        return True

    def signal_quit(self, *args) -> None:
        log("quit%s", args)
        self.close()

    def cancel(self, *args):
        log("cancel%s", args)
        self.cancel_btn.activate()

    def password_activate(self, *_args):
        self.confirm_btn.activate()

    def password_changed(self, *_args):
        self.password = self.password_input.get_text()

    def get_password(self) -> str:
        return self.password


def show_pass_dialog(argv):
    from xpra.platform.gui import ready as gui_ready, init as gui_init, set_default_icon

    set_default_icon("authentication.png")
    gui_init()

    log("show_pass_dialog(%s)", argv)

    def arg(n):
        if len(argv) <= n:
            return ""
        return argv[n].replace("\\n\\r", "\\n").replace("\\n", "\n")

    title = arg(0) or "Enter Password"
    prompt = arg(1)
    icon = arg(2)
    app = PasswordInputDialogWindow(title, prompt, icon)
    register_os_signals(app.signal_quit, "Password Dialog")
    gui_ready()
    app.show()
    p = app.run()
    if p is not None:
        sys.stdout.write(p)
        sys.stdout.flush()
        return 0
    return 1


def main() -> int:
    from xpra.platform import program_context
    with program_context("Password-Input-Dialog", "Password Input Dialog"):
        if "-v" in sys.argv:
            from xpra.log import enable_debug_for
            enable_debug_for("util")

        try:
            return show_pass_dialog(sys.argv[1:])
        except KeyboardInterrupt:
            return 1


if __name__ == "__main__":
    v = main()
    sys.exit(v)
