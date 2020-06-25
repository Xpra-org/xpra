# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
from gi.repository import Gtk, GdkPixbuf, GLib, Pango

from xpra import __version__
from xpra.gtk_common.quit import gtk_main_quit_really, gtk_main_quit_on_fatal_exceptions_enable
from xpra.gtk_common.gtk_util import add_close_accel
from xpra.gtk_common.gobject_compat import install_signal_handlers
from xpra.client.gtk_base.css_overrides import inject_css_overrides
from xpra.platform.paths import get_icon_filename
from xpra.os_util import POSIX
from xpra.log import Logger

log = Logger("client", "util")

inject_css_overrides()


class SplashScreen(Gtk.Window):

    def __init__(self):
        self.exit_code = None
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.connect("delete_event", self.exit)
        self.set_title("Splash")
        self.set_size_request(320, 160)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_decorated(False)
        vbox = Gtk.VBox()
        hbox = Gtk.HBox(homogeneous=False)
        icon = self.get_pixbuf("xpra")
        if icon:
            self.set_icon(icon)
            hbox.pack_start(Gtk.Image.new_from_pixbuf(icon), False, False, 20)
        self.label = Gtk.Label(label="Xpra %s" % __version__)
        self.label.modify_font(Pango.FontDescription("sans 18"))
        hbox.pack_start(self.label, True, True, 20)
        vbox.add(hbox)
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_size_request(320, 30)
        vbox.add(self.progress_bar)
        self.add(vbox)
        self.stdin_io_watch = 0
        self.stdin_buffer = ""
        install_signal_handlers(None, self.handle_signal)
        self.opacity = 100


    def run(self):
        self.start_stdin_io()
        self.show_all()
        self.present()
        gtk_main_quit_on_fatal_exceptions_enable()
        Gtk.main()
        return self.exit_code or 0

    def start_stdin_io(self):
        stdin = sys.stdin
        fileno = stdin.fileno()
        if POSIX:
            import fcntl
            fl = fcntl.fcntl(fileno, fcntl.F_GETFL)
            fcntl.fcntl(fileno, fcntl.F_SETFL, fl | os.O_NONBLOCK)
        self.stdin_io_watch = GLib.io_add_watch(sys.stdin,
                                                GLib.PRIORITY_DEFAULT, GLib.IO_IN,
                                                self.stdin_ready)

    def stdin_ready(self, *_args):
        data = sys.stdin.read()
        #print("data=%s" % (data,))
        self.stdin_buffer += data
        #print("stdin_buffer=%s" % (self.stdin_buffer,))
        self.process_stdin_buffer()
        return True

    def process_stdin_buffer(self):
        buf = self.stdin_buffer
        while True:
            pos = buf.find("\n")
            if pos<0:
                break
            line = buf[:pos].strip("\n\r")
            buf = buf[pos+1:]
            if line:
                self.handle_stdin_line(line)
        self.stdin_buffer = buf

    def handle_stdin_line(self, line):
        parts = line.split(":")
        if parts[0]:
            try:
                pct = int(parts[0])
            except ValueError:
                pass
            else:
                self.progress_bar.set_fraction(pct/100.0)
                if pct==100:
                    GLib.timeout_add(20, self.fade_out)
                    GLib.timeout_add(1500, self.exit)
        if len(parts)>=2:
            self.progress_bar.set_text(parts[1])
            self.progress_bar.set_show_text(True)

    def fade_out(self):
        self.opacity = max(0, self.opacity-2)
        self.set_opacity(self.opacity/100.0)
        return self.opacity>0

    def exit(self, *args):
        log("exit%s calling %s", args, gtk_main_quit_really)
        gtk_main_quit_really()
        siw = self.stdin_io_watch
        if siw:
            self.stdin_io_watch = 0
            GLib.source_remove(siw)


    def handle_signal(self, signum, _frame=None):
        self.exit_code = 128-(signum or 0)
        GLib.idle_add(self.exit)

    def get_pixbuf(self, icon_name):
        try:
            if not icon_name:
                log("get_pixbuf(%s)=None", icon_name)
                return None
            icon_filename = get_icon_filename(icon_name)
            log("get_pixbuf(%s) icon_filename=%s", icon_name, icon_filename)
            if icon_filename:
                return GdkPixbuf.Pixbuf.new_from_file(icon_filename)
        except Exception:
            log.error("get_pixbuf(%s)", icon_name, exc_info=True)
        return None


def main(args):
    from xpra.platform import program_context
    with program_context("splash", "Splash"):
        w = SplashScreen()
        add_close_accel(w, Gtk.main_quit)
        return w.run()


if __name__ == "__main__":
    main(sys.argv)
    sys.exit(0)
