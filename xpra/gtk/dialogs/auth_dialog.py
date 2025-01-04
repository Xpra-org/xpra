# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from xpra.gtk.window import add_close_accel
from xpra.gtk.widget import label
from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.gtk.signals import register_os_signals
from xpra.os_util import gi_import
from xpra.log import Logger

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")

log = Logger("util")


class AuthDialog(Gtk.Window):

    def __init__(self, title="Session Access Request", info="unknown user from unknown location", timeout=600):
        super().__init__()
        self.timeout = timeout
        self.exit_code = 1
        self.set_title(title)
        self.set_resizable(True)
        self.set_decorated(True)
        # pylint: disable=no-member
        self.set_border_width(20)
        icon = get_icon_pixbuf("authentication.png")
        if icon:
            self.set_icon(icon)
        add_close_accel(self, self.quit)
        self.connect("delete_event", self.quit)

        self.vbox = Gtk.VBox(homogeneous=False, spacing=20)
        self.add(self.vbox)

        title_label = label(title, font="sans 14")
        self.vbox.add(title_label)

        info_label = label(info, font="sans 12")
        self.vbox.add(info_label)

        if self.timeout > 0:
            self.timeout_label = label()
            self.update_timeout()
            self.vbox.add(self.timeout_label)
            GLib.timeout_add(1000, self.update_timeout)

        al = Gtk.Alignment(xalign=1.0, yalign=0.5, xscale=0.0, yscale=0.0)
        al.set_padding(0, 0, 10, 10)
        hbox = Gtk.HBox(homogeneous=False, spacing=10)
        al.add(hbox)
        hbox.add(self.btn("Cancel", Gtk.STOCK_NO, self.cancel))
        hbox.add(self.btn("Accept", Gtk.STOCK_OK, self.accept))
        self.vbox.add(al)

        register_os_signals(self.app_signal, "Authentication Dialog")
        self.show_all()

    @staticmethod
    def btn(label, stock_icon, callback):
        btn = Gtk.Button(label=label)
        settings = btn.get_settings()
        settings.set_property('gtk-button-images', True)
        btn.connect("clicked", callback)
        if stock_icon:
            # pylint: disable=no-member
            image = Gtk.Image.new_from_stock(stock_icon, Gtk.IconSize.BUTTON)
            if image:
                btn.set_image(image)
        return btn

    def update_timeout(self):
        if self.timeout <= 0:
            self.exit_code = 2
            self.quit()
            return False
        self.timeout_label.set_text(f"This request will timeout in {self.timeout} seconds")
        self.timeout -= 1
        return True

    def cancel(self, _btn):
        self.exit_code = 3
        self.quit()

    def accept(self, _btn):
        self.exit_code = 0
        self.quit()

    def quit(self, *args):
        log("quit%s", args)
        self.do_quit()

    @staticmethod
    def do_quit():
        log("do_quit()")
        Gtk.main_quit()

    def app_signal(self, signum):
        self.exit_code = 128 + signum
        log("app_signal(%s) exit_code=%i", signum, self.exit_code)
        self.do_quit()


def main():
    # pylint: disable=import-outside-toplevel
    from xpra.util.io import stderr_print
    from xpra.platform import program_context
    with program_context("Session Access"):
        from xpra.platform.gui import init as gui_init
        gui_init()
        if len(sys.argv) < 2:
            stderr_print(f"usage: {sys.argv[0]} 'message' [timeout-in-seconds]")
            return 4
        info = sys.argv[1]
        if len(sys.argv) >= 3:
            try:
                timeout = int(sys.argv[2])
            except ValueError:
                stderr_print("invalid timeout value")
                stderr_print(f"usage: {sys.argv[0]} 'message' [timeout-in-seconds]")
                return 4
        else:
            timeout = 600
        w = AuthDialog(info=info, timeout=timeout)
        Gtk.main()
        return w.exit_code


if __name__ == "__main__":
    r = main()
    sys.exit(r)
