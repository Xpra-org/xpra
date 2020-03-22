#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


import os.path
import sys

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Pango", "1.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Pango, Gtk, GdkPixbuf

from xpra.gtk_common.gobject_compat import register_os_signals
from xpra.gtk_common.gtk_util import add_close_accel, color_parse
from xpra.platform.gui import force_focus
from xpra.platform.paths import get_icon_dir
from xpra.os_util import get_util_logger

log = get_util_logger()


class ConfirmDialogWindow(Gtk.Dialog):

    def __init__(self, title="Title", prompt="", info=(), icon="", buttons=()):
        log("ConfirmDialogWindow%s", (title, prompt, info, icon, buttons))
        super().__init__()
        self.set_border_width(20)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("delete-event", self.quit)
        self.set_default_size(400, 150)
        self.set_title(title)
        add_close_accel(self, self.quit)

        if icon:
            icon_filename = os.path.join(get_icon_dir(), icon)
            if os.path.exists(icon_filename):
                icon_pixbuf = GdkPixbuf.Pixbuf.new_from_file(icon_filename)
                if icon_pixbuf:
                    self.set_icon(icon_pixbuf)

        vbox = self.get_content_area()
        vbox.set_spacing(10)

        def al(label, font="sans 14", xalign=0):
            l = Gtk.Label(label=label)
            l.modify_font(Pango.FontDescription(font))
            if label.startswith("WARNING"):
                red = color_parse("red")
                l.modify_fg(Gtk.StateType.NORMAL, red)
            al = Gtk.Alignment(xalign=xalign, yalign=0.5, xscale=0.0, yscale=0)
            al.add(l)
            al.show_all()
            return al
        vbox.add(al(title, "sans 18", 0.5))
        info_box = Gtk.VBox()
        for i in info:
            info_box.add(al(i, "sans 14"))
        info_box.show_all()
        vbox.add(info_box)
        vbox.add(al(prompt, "sans 14"))

        # Buttons:
        for label, code in buttons:
            btn = self.add_button(label, code)
            btn.set_size_request(100, 48)

    def quit(self, *args):
        log("quit%s", args)
        self.destroy()
        return True


def show_confirm_dialog(argv):
    from xpra.platform.gui import ready as gui_ready
    from xpra.gtk_common.quit import gtk_main_quit_on_fatal_exceptions_enable
    from xpra.platform.gui import init as gui_init, set_default_icon

    set_default_icon("information.png")
    gui_init()

    gtk_main_quit_on_fatal_exceptions_enable()

    log("show_confirm_dialog(%s)", argv)
    def arg(n):
        if len(argv)<=n:
            return ""
        return argv[n].replace("\\n\\r", "\\n").replace("\\n", "\n")
    title = arg(0) or "Confirm Key"
    prompt = arg(1)
    info = arg(2)
    icon = arg(3)
    buttons = []
    n = 4
    while len(argv)>(n+1):
        label = arg(n)
        try:
            code = int(arg(n+1))
        except ValueError as e:
            log.error("Error: confirm dialog cannot parse code '%s': %s", arg(n+1), e)
            return 1
        buttons.append((label, code))
        n += 2
    app = ConfirmDialogWindow(title, prompt, info, icon, buttons)
    register_os_signals(app.quit, "Dialog")
    gui_ready()
    force_focus()
    app.show_all()
    app.present()
    return app.run()


def main():
    from xpra.platform import program_context
    with program_context("Confirm-Dialog", "Confirm Dialog"):
        #logging init:
        if "-v" in sys.argv or "--verbose" in sys.argv:
            from xpra.log import enable_debug_for
            enable_debug_for("util")

        try:
            return show_confirm_dialog(sys.argv[1:])
        except KeyboardInterrupt:
            return 1


if __name__ == "__main__":
    v = main()
    sys.exit(v)
