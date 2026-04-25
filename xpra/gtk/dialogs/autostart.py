#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import signal

from xpra.os_util import gi_import
from xpra.exit_codes import ExitValue
from xpra.platform.gui import init as gui_init, force_focus
from xpra.gtk.util import gtk_main
from xpra.gtk.window import add_close_accel
from xpra.gtk.widget import scaled_image, label
from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.log import Logger, consume_verbose_argv

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")

log = Logger("util")


def _get_status() -> str:
    from xpra.platform.autostart import get_status  # pylint: disable=import-outside-toplevel
    return get_status()


class AutostartWindow:

    def __init__(self):
        self.window = Gtk.Window()
        self.window.set_border_width(40)
        self.window.connect("delete-event", self.close)
        self.window.set_default_size(320, 160)
        self.window.set_title("Xpra Autostart")
        self.window.set_position(Gtk.WindowPosition.CENTER)

        icon = get_icon_pixbuf("xpra.png")
        if icon:
            self.window.set_icon(icon)

        vbox = Gtk.VBox(homogeneous=False, spacing=16)

        # status label
        self.status_label = label("", font="sans 14")
        vbox.pack_start(self.status_label, False, False, 0)

        # switch + label in an hbox
        hbox_switch = Gtk.HBox(homogeneous=False, spacing=8)
        hbox_switch.pack_start(label("Start Xpra at login", font="sans 12"), False, False, 0)
        self.toggle = Gtk.Switch()
        self.toggle.connect("notify::active", self._on_toggled)
        hbox_switch.pack_start(self.toggle, False, False, 20)
        vbox.pack_start(hbox_switch, False, False, 0)

        # error label (hidden unless something goes wrong)
        self.error_label = label("", font="sans 10")
        self.error_label.set_line_wrap(True)
        vbox.pack_start(self.error_label, False, False, 0)

        # close button
        hbox = Gtk.HBox(homogeneous=False, spacing=0)
        close_btn = Gtk.Button(label="Close")
        close_btn.connect("clicked", self.close)
        close_icon = get_icon_pixbuf("quit.png")
        if close_icon:
            close_btn.set_image(scaled_image(close_icon, 24))
        hbox.pack_end(close_btn, False, False, 0)
        vbox.pack_start(hbox, False, False, 0)

        add_close_accel(self.window, self.close)
        vbox.show_all()
        self.window.add(vbox)

        self._refresh()

    def _refresh(self) -> None:
        status = _get_status()
        enabled = status == "enabled"
        log("_refresh() status=%r enabled=%s", status, enabled)
        # block the toggled signal while we set state programmatically
        self.toggle.handler_block_by_func(self._on_toggled)
        self.toggle.set_active(enabled)
        self.toggle.handler_unblock_by_func(self._on_toggled)
        self.status_label.set_text(f"Autostart is currently: {status}")
        self.error_label.set_text("")

    def _on_toggled(self, *_args) -> None:
        enabled = self.toggle.get_active()
        log("_on_toggled() enabled=%s", enabled)
        try:
            from xpra.platform.autostart import set_autostart  # pylint: disable=import-outside-toplevel
            set_autostart(enabled)
        except Exception as e:
            log("set_autostart(%s)", enabled, exc_info=True)
            self.error_label.set_text(f"Error: {e}")
        self._refresh()

    def show(self) -> None:
        def _show() -> None:
            force_focus()
            self.window.show_all()
            self.window.present()
        GLib.idle_add(_show)

    def close(self, *_args) -> bool:
        self.do_close()
        return True

    def do_close(self) -> None:
        self.window.hide()

    def destroy(self, *_args) -> None:
        if self.window:
            self.window.destroy()
            self.window = None

    @staticmethod
    def run() -> ExitValue:
        gtk_main()
        return 0

    def quit(self, *_args) -> None:
        self.window.hide()
        Gtk.main_quit()


def main(argv: list[str]) -> int:
    from xpra.platform import program_context
    from xpra.platform.gui import ready as gui_ready
    with program_context("Xpra-Autostart", "Xpra Autostart"):
        consume_verbose_argv(argv, "util")

        from xpra.util.glib import register_os_signals
        app = AutostartWindow()
        app.do_close = app.quit
        register_os_signals(app.quit, "Autostart")
        try:
            gui_ready()
            app.show()
            return app.run()
        except KeyboardInterrupt:
            return 128 + int(signal.SIGINT)


if __name__ == "__main__":
    gui_init()
    v = main(sys.argv)
    sys.exit(v)
