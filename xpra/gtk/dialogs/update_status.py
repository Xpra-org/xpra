#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2017-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from collections.abc import Callable

from xpra.os_util import gi_import
from xpra.platform.gui import init as gui_init, force_focus
from xpra.gtk.window import add_close_accel
from xpra.gtk.widget import scaled_image, label
from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.log import Logger, enable_debug_for

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")

log = Logger("util")


_instance = None


def get_update_status_window():
    global _instance
    if _instance is None:
        _instance = UpdateStatusWindow()
    return _instance


class UpdateStatusWindow:

    def __init__(self):
        self.window = Gtk.Window()
        self.window.set_border_width(20)
        self.window.connect("delete-event", self.close)
        self.window.set_default_size(400, 200)
        self.window.set_title("Xpra Version Check")

        icon = get_icon_pixbuf("update.png")
        if icon:
            self.window.set_icon(icon)
        self.window.set_position(Gtk.WindowPosition.CENTER)

        vbox = Gtk.VBox(homogeneous=False, spacing=0)
        vbox.set_spacing(0)

        # Label:
        self.progress = 0
        self.label = label("Version Check", font="sans 14")
        al = Gtk.Alignment(xalign=0, yalign=0.5, xscale=0.0, yscale=0)
        al.add(self.label)
        vbox.add(al)

        # Buttons:
        hbox = Gtk.HBox(homogeneous=False, spacing=20)
        vbox.pack_start(hbox)

        def btn(label: str, tooltip: str, callback: Callable, icon_name: str = ""):
            btn = Gtk.Button(label=label)
            btn.set_tooltip_text(tooltip)
            btn.connect("clicked", callback)
            icon = get_icon_pixbuf(icon_name)
            if icon:
                btn.set_image(scaled_image(icon, 24))
            hbox.pack_start(btn)
            return btn
        btn("Download", "Show download page", self.download, "download.png")
        btn("Close", "", self.close, "quit.png")

        def accel_close(*_args):
            self.close()
        add_close_accel(self.window, accel_close)
        vbox.show_all()
        self.window.vbox = vbox
        self.window.add(vbox)
        self.newer_version : None |bool |tuple[int,...] = None

    def check(self):
        if self.progress:
            return
        self.newer_version = None
        GLib.timeout_add(1000, self.update_label)
        from xpra.util.thread import start_thread
        start_thread(self.do_check, "version check", daemon=True)

    def do_check(self):
        from xpra.util.version import version_update_check
        try:
            self.newer_version = version_update_check()
        finally:
            self.progress = 0

    def update_label(self):
        if self.newer_version is False:
            from xpra import __version__ as version_str
            self.label.set_label("Version %s is up to date" % version_str)
            return False
        if self.newer_version:
            version_str = ".".join(str(x) for x in self.newer_version)
            self.label.set_label("A newer version is available: %s" % version_str)
            return False
        self.label.set_label("Checking for new versions %s" % (["-", "\\", "|", "/"][self.progress % 4]))
        self.progress += 1
        return True

    def show(self):
        log("show()")

        def show():
            force_focus()
            self.window.show()
            self.window.present()
        GLib.idle_add(show)

    def hide(self):
        log("hide()")
        self.window.hide()

    def close(self, *args):
        log("close%s", args)
        self.hide()
        return True

    def destroy(self, *args):
        log("destroy%s", args)
        if self.window:
            self.window.destroy()
            self.window = None

    def run(self) -> None:
        log("run()")
        Gtk.main()
        log("run() Gtk.main done")

    def quit(self, *args):
        log("quit%s", args)
        self.close()
        Gtk.main_quit()

    def download(self, *_args):
        self.hide()
        import webbrowser
        webbrowser.open_new_tab("https://github.com/Xpra-org/xpra/wiki/Download")


def main():
    from xpra.platform import program_context
    from xpra.platform.gui import ready as gui_ready
    with program_context("Xpra-Version-Check", "Xpra Version Check"):
        if "-v" in sys.argv:
            enable_debug_for("util")

        from xpra.gtk.signals import register_os_signals
        app = UpdateStatusWindow()
        app.close = app.quit
        register_os_signals(app.quit, "Version Check")
        try:
            gui_ready()
            app.show()
            app.check()
            app.run()
        except KeyboardInterrupt:
            pass
        return 0


if __name__ == "__main__":
    gui_init()
    v = main()
    sys.exit(v)
