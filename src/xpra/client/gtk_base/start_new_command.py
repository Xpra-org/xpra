#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


import os.path
import sys
import signal

from xpra.platform.gui import init as gui_init
gui_init()

from xpra.gtk_common.gobject_compat import import_gtk, import_gdk, import_gobject, import_pango

gtk = import_gtk()
gdk = import_gdk()
gobject = import_gobject()
gobject.threads_init()
pango = import_pango()


from xpra.gtk_common.gtk_util import gtk_main, add_close_accel, scaled_image, pixbuf_new_from_file, \
                                    WIN_POS_CENTER, STATE_NORMAL
from xpra.platform.paths import get_icon_dir
from xpra.log import Logger, enable_debug_for
log = Logger("util")


_instance = None
def getStartNewCommand(run_callback, can_share=False):
    global _instance
    if _instance is None:
        _instance = StartNewCommand(run_callback, can_share)
    return _instance


class StartNewCommand(object):

    def __init__(self, run_callback=None, can_share=False):
        self.run_callback = run_callback
        self.window = gtk.Window()
        self.window.connect("destroy", self.close)
        self.window.set_default_size(400, 150)
        self.window.set_border_width(20)
        self.window.set_title("Start New Command")
        self.window.modify_bg(STATE_NORMAL, gdk.Color(red=65535, green=65535, blue=65535))

        icon_pixbuf = self.get_icon("forward.png")
        if icon_pixbuf:
            self.window.set_icon(icon_pixbuf)
        self.window.set_position(WIN_POS_CENTER)

        vbox = gtk.VBox(False, 0)
        vbox.set_spacing(0)

        # Label:
        label = gtk.Label("Command to run:")
        label.modify_font(pango.FontDescription("sans 14"))
        al = gtk.Alignment(xalign=0, yalign=0.5, xscale=0.0, yscale=0)
        al.add(label)
        vbox.add(al)

        # Actual command:
        self.entry = gtk.Entry(max=100)
        self.entry.set_width_chars(32)
        self.entry.connect('activate', self.run_command)
        vbox.add(self.entry)

        if can_share:
            self.share = gtk.CheckButton("Shared", use_underline=False)
            #Shared commands will also be shown to other clients
            self.share.set_active(True)
            vbox.add(self.share)
        else:
            self.share = None

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
        btn("Run", "Run this command", self.run_command, "forward.png")
        btn("Cancel", "", self.close, "quit.png")

        def accel_close(*_args):
            self.close()
        add_close_accel(self.window, accel_close)
        vbox.show_all()
        self.window.vbox = vbox
        self.window.add(vbox)


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


    def run_command(self, *_args):
        self.hide()
        command = self.entry.get_text()
        if self.run_callback:
            self.run_callback(command, self.share is None or self.share.get_active())


def main():
    from xpra.platform import program_context
    from xpra.platform.gui import ready as gui_ready
    with program_context("Start-New-Command", "Start New Command"):
        #logging init:
        if "-v" in sys.argv:
            enable_debug_for("util")

        from xpra.os_util import SIGNAMES
        from xpra.gtk_common.quit import gtk_main_quit_on_fatal_exceptions_enable
        gtk_main_quit_on_fatal_exceptions_enable()

        app = StartNewCommand()
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
            app.run()
        except KeyboardInterrupt:
            pass
        return 0


if __name__ == "__main__":
    v = main()
    sys.exit(v)
