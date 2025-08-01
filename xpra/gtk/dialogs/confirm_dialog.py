#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from xpra.util.glib import register_os_signals
from xpra.gtk.window import add_close_accel
from xpra.gtk.widget import label, modify_fg, color_parse
from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.platform.gui import force_focus
from xpra.os_util import gi_import
from xpra.util.io import get_util_logger

Gtk = gi_import("Gtk")
GdkPixbuf = gi_import("GdkPixbuf")

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

        icon_pixbuf = get_icon_pixbuf(icon)
        if icon_pixbuf:
            self.set_icon(icon_pixbuf)

        vbox = self.get_content_area()
        vbox.set_spacing(10)

        def al(text: str, font="sans 14", xalign=0.0) -> Gtk.Alignment:
            lbl = label(text, font=font)
            if text.startswith("WARNING"):
                modify_fg(lbl, color_parse("red"))
            align = Gtk.Alignment(xalign=xalign, yalign=0.5, xscale=0.0, yscale=0)
            align.add(lbl)
            align.show_all()
            return align

        vbox.add(al(title, "sans 18", 0.5))
        info_box = Gtk.VBox()
        for i in info:
            info_box.add(al(i))
        info_box.show_all()
        vbox.add(info_box)
        vbox.add(al(prompt))

        # Buttons:
        for txt, code in buttons:
            btn = self.add_button(txt, code)
            btn.set_size_request(100, 48)

    def quit(self, *args) -> bool:
        log("quit%s", args)
        self.destroy()
        return True

    def signal_quit(self, *args) -> None:
        log("signal_quit%s", args)
        self.close()


def show_confirm_dialog(argv) -> int:
    from xpra.platform.gui import ready as gui_ready, init as gui_init, set_default_icon

    set_default_icon("information.png")
    gui_init()

    log("show_confirm_dialog(%s)", argv)

    def arg(i: int) -> str:
        if len(argv) <= i:
            return ""
        return argv[i].replace("\\n\\r", "\\n").replace("\\n", "\n")

    title = arg(0) or "Confirm Key"
    prompt = arg(1)
    info = arg(2)
    icon = arg(3)
    buttons = []
    n = 4
    while len(argv) > (n + 1):
        text = arg(n)
        try:
            code = int(arg(n + 1))
        except ValueError as e:
            log.error("Error: confirm dialog cannot parse code '%s': %s", arg(n + 1), e)
            return 1
        buttons.append((text, code))
        n += 2
    app = ConfirmDialogWindow(title, prompt, info, icon, buttons)
    register_os_signals(app.signal_quit, "Dialog")
    gui_ready()
    force_focus()
    app.show_all()
    app.present()
    return app.run()


def main(args):
    from xpra.log import consume_verbose_argv
    from xpra.platform import program_context
    with program_context("Confirm-Dialog", "Confirm Dialog"):
        consume_verbose_argv(args, "util",)
        try:
            return show_confirm_dialog(args[1:])
        except KeyboardInterrupt:
            return 1


if __name__ == "__main__":
    v = main(sys.argv)
    sys.exit(v)
