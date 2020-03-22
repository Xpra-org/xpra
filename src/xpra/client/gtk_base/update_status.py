#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2017-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Pango", "1.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GLib, Pango, Gtk, GdkPixbuf

from xpra.platform.gui import init as gui_init, force_focus
from xpra.gtk_common.gtk_util import (
    add_close_accel, scaled_image,
    )
from xpra.platform.paths import get_icon_dir
from xpra.log import Logger, enable_debug_for

log = Logger("util")


_instance = None
def getUpdateStatusWindow():
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

        icon = self.get_icon("update.png")
        if icon:
            self.window.set_icon(icon)
        self.window.set_position(Gtk.WindowPosition.CENTER)

        vbox = Gtk.VBox(False, 0)
        vbox.set_spacing(0)

        # Label:
        self.progress = 0
        self.label = Gtk.Label("Version Check")
        self.label.modify_font(Pango.FontDescription("sans 14"))
        al = Gtk.Alignment(xalign=0, yalign=0.5, xscale=0.0, yscale=0)
        al.add(self.label)
        vbox.add(al)

        # Buttons:
        hbox = Gtk.HBox(False, 20)
        vbox.pack_start(hbox)
        def btn(label, tooltip, callback, icon_name=None):
            btn = Gtk.Button(label)
            btn.set_tooltip_text(tooltip)
            btn.connect("clicked", callback)
            if icon_name:
                icon = self.get_icon(icon_name)
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


    def check(self):
        if self.progress:
            return
        self.newer_version = None
        GLib.timeout_add(1000, self.update_label)
        from xpra.make_thread import start_thread
        start_thread(self.do_check, "version check", daemon=True)

    def do_check(self):
        from xpra.version_util import version_update_check
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
        self.label.set_label("Checking for new versions %s" % (["-", "\\", "|", "/"][self.progress%4]))
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


    def run(self):
        log("run()")
        Gtk.main()
        log("run() Gtk.main done")

    def quit(self, *args):
        log("quit%s", args)
        self.destroy()
        Gtk.main_quit()


    def get_icon(self, icon_name):
        icon_filename = os.path.join(get_icon_dir(), icon_name)
        if os.path.exists(icon_filename):
            return GdkPixbuf.Pixbuf.new_from_file(icon_filename)
        return None


    def download(self, *_args):
        self.hide()
        import webbrowser
        webbrowser.open_new_tab("https://xpra.org/trac/wiki/Download")


def main():
    from xpra.platform import program_context
    from xpra.platform.gui import ready as gui_ready
    with program_context("Xpra-Version-Check", "Xpra Version Check"):
        #logging init:
        if "-v" in sys.argv:
            enable_debug_for("util")

        from xpra.gtk_common.quit import gtk_main_quit_on_fatal_exceptions_enable
        gtk_main_quit_on_fatal_exceptions_enable()

        from xpra.gtk_common.gobject_compat import register_os_signals
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
