# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path
import subprocess

from xpra.gtk_common.gobject_compat import import_gtk, import_gdk, import_pango, import_glib
gtk = import_gtk()
gdk = import_gdk()
pango = import_pango()
glib = import_glib()
glib.threads_init()

from xpra.platform.paths import get_icon_dir, get_xpra_command
from xpra.os_util import OSX, WIN32
from xpra.gtk_common.gtk_util import gtk_main, add_close_accel, pixbuf_new_from_file, add_window_accel, imagebutton, WIN_POS_CENTER
from xpra.log import Logger
log = Logger("client", "util")


class GUI(gtk.Window):

    def __init__(self, title="Xpra"):
        self.exit_code = 0
        gtk.Window.__init__(self)
        self.set_title(title)
        self.set_border_width(10)
        self.set_resizable(True)
        self.set_decorated(True)
        self.set_position(WIN_POS_CENTER)
        self.set_size_request(640, 300)
        icon = self.get_pixbuf("xpra")
        if icon:
            self.set_icon(icon)
        add_close_accel(self, self.quit)
        add_window_accel(self, 'F1', self.show_about)
        self.connect("delete_event", self.quit)

        self.vbox = gtk.VBox(False, 10)
        self.add(self.vbox)
        #with most window managers,
        #the window's title bar already shows "Xpra"
        #title_label = gtk.Label(title)
        #title_label.modify_font(pango.FontDescription("sans 14"))
        #self.vbox.add(title_label)
        label_font = pango.FontDescription("sans 16")
        icon = self.get_pixbuf("browse.png")
        self.browse_button = imagebutton("Browse", icon, "Browse and connect to local sessions", clicked_callback=self.browse, icon_size=48, label_font=label_font)
        icon = self.get_pixbuf("connect.png")
        self.connect_button = imagebutton("Connect", icon, "Connect to a session", clicked_callback=self.show_launcher, icon_size=48, label_font=label_font)
        icon = self.get_pixbuf("server-connected.png")
        self.shadow_button = imagebutton("Shadow", icon, "Start a shadow server", clicked_callback=self.start_shadow, icon_size=48, label_font=label_font)
        #some builds don't have server / shadow support:
        try:
            from xpra.server import shadow
            assert shadow
        except ImportError:
            self.shadow_button.set_tooltip_text("This build of Xpra does not support starting sessions")
            self.shadow_button.set_sensitive(False)
        icon = self.get_pixbuf("windows.png")
        self.start_button = imagebutton("Start", icon, "Start a session", clicked_callback=self.start, icon_size=48, label_font=label_font)
        #not all builds and platforms can start sessions:
        if OSX or WIN32:
            self.start_button.set_tooltip_text("Starting sessions is not supported on %s" % sys.platform)
        else:
            try:
                from xpra import server
                assert server
            except ImportError:
                self.start_button.set_tooltip_text("This build of Xpra does not support starting sessions")
        self.start_button.set_sensitive(False)
        table = gtk.Table(2, 2, True)
        for i, widget in enumerate((self.browse_button, self.connect_button, self.shadow_button, self.start_button)):
            table.attach(widget, i%2, i%2+1, i//2, i//2+1, xpadding=10, ypadding=10)
        self.vbox.add(table)
        self.show_all()

    def quit(self, *args):
        log("quit%s", args)
        self.do_quit()

    def do_quit(self):
        log("do_quit()")
        gtk.main_quit()

    def app_signal(self, signum, frame):
        self.exit_code = 128 + signum
        log("app_signal(%s, %s) exit_code=%i", signum, frame, self.exit_code)
        self.do_quit()

    def get_pixbuf(self, icon_name):
        icon_filename = os.path.join(get_icon_dir(), icon_name)
        if os.path.exists(icon_filename):
            return pixbuf_new_from_file(icon_filename)
        return None

    def show_about(self, *args):
        from xpra.gtk_common.about import about
        about()


    def exec_command(self, cmd):
        proc = subprocess.Popen(cmd)
        log("exec_command(%s)=%s", cmd, proc)

    def start_shadow(self, *_args):
        cmd = get_xpra_command()+["shadow"]
        self.exec_command(cmd)

    def browse(self, *_args):
        cmd = get_xpra_command()+["mdns-gui"]
        self.exec_command(cmd)

    def show_launcher(self, *_args):
        cmd = get_xpra_command()+["launcher"]
        self.exec_command(cmd)

    def start(self, *args):
        #TODO: show start gui
        pass


def main():
    from xpra.platform import program_context
    from xpra.log import enable_color
    with program_context("Xpra-GUI", "Xpra GUI"):
        enable_color()
        gui = GUI()
        import signal
        signal.signal(signal.SIGINT, gui.app_signal)
        signal.signal(signal.SIGTERM, gui.app_signal)
        gtk_main()
        log("do_main() gui.exit_code=%i", gui.exit_code)
        return 0


if __name__ == "__main__":
    r = main()
    sys.exit(r)
