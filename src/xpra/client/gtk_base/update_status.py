#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


import os.path
import sys
import signal

from xpra.platform.gui import init as gui_init
gui_init()

from xpra.gtk_common.gobject_compat import import_gtk, import_gdk, import_pango, import_glib

gtk = import_gtk()
gdk = import_gdk()
pango = import_pango()
glib = import_glib()


from xpra.gtk_common.gtk_util import gtk_main, add_close_accel, scaled_image, pixbuf_new_from_file, \
                                    WIN_POS_CENTER, STATE_NORMAL
from xpra.platform.paths import get_icon_dir
from xpra.log import Logger, enable_debug_for
log = Logger("util")


_instance = None
def getUpdateStatusWindow():
    global _instance
    if _instance is None:
        _instance = UpdateStatusWindow()
    return _instance


class UpdateStatusWindow(object):

    def __init__(self):
        self.window = gtk.Window()
        self.window.connect("destroy", self.close)
        self.window.set_default_size(400, 200)
        self.window.set_border_width(20)
        self.window.set_title("Xpra Version Check")
        self.window.modify_bg(STATE_NORMAL, gdk.Color(red=65535, green=65535, blue=65535))

        icon = self.get_icon("update.png")
        if icon:
            self.window.set_icon(icon)
        self.window.set_position(WIN_POS_CENTER)

        vbox = gtk.VBox(False, 0)
        vbox.set_spacing(0)

        # Label:
        self.progress = 0
        self.label = gtk.Label("Version Check")
        self.label.modify_font(pango.FontDescription("sans 14"))
        al = gtk.Alignment(xalign=0, yalign=0.5, xscale=0.0, yscale=0)
        al.add(self.label)
        vbox.add(al)

        # Buttons:
        hbox = gtk.HBox(False, 20)
        vbox.pack_start(hbox)
        def btn(label, tooltip, callback, icon_name=None):
            btn = gtk.Button(label)
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
        glib.timeout_add(1000, self.update_label)
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
        elif self.newer_version:
            version_str = ".".join(str(x) for x in self.newer_version)
            self.label.set_label("A newer version is available: %s" % version_str)
            return False
        self.label.set_label("Checking for new versions %s" % (["-", "\\", "|", "/"][self.progress%4]))
        self.progress += 1
        return True

    def show(self):
        log("show()")
        self.window.show()
        self.window.present()

    def hide(self):
        log("hide()")
        self.window.hide()

    def close(self, *args):
        log("close%s", args)
        self.hide()

    def destroy(self, *args):
        log("destroy%s", args)
        if self.window:
            self.window.destroy()
            self.window = None


    def run(self):
        log("run()")
        gtk_main()
        log("run() gtk_main done")

    def quit(self, *args):
        log("quit%s", args)
        self.destroy()
        gtk.main_quit()


    def get_icon(self, icon_name):
        icon_filename = os.path.join(get_icon_dir(), icon_name)
        if os.path.exists(icon_filename):
            return pixbuf_new_from_file(icon_filename)
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

        from xpra.os_util import SIGNAMES
        from xpra.gtk_common.quit import gtk_main_quit_on_fatal_exceptions_enable
        gtk_main_quit_on_fatal_exceptions_enable()

        app = UpdateStatusWindow()
        app.close = app.quit
        def app_signal(signum, _frame):
            print("")
            log.info("got signal %s", SIGNAMES.get(signum, signum))
            app.quit()
        signal.signal(signal.SIGINT, app_signal)
        signal.signal(signal.SIGTERM, app_signal)
        try:
            gui_ready()
            app.show()
            app.check()
            app.run()
        except KeyboardInterrupt:
            pass
        return 0


if __name__ == "__main__":
    v = main()
    sys.exit(v)
