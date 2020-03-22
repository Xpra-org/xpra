# This file is part of Xpra.
# Copyright (C) 2017-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Pango", "1.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GLib, Pango, Gtk, GdkPixbuf

from xpra.gtk_common.gtk_util import add_close_accel
from xpra.gtk_common.gobject_compat import register_os_signals
from xpra.platform.paths import get_icon_dir
from xpra.log import Logger

log = Logger("util")


class AuthDialog(Gtk.Window):

    def __init__(self, title="Session Access Request", info="unknown user from unknown location", timeout=600):
        Gtk.Window.__init__(self)
        self.timeout = timeout
        self.exit_code = 1
        self.set_title(title)
        self.set_border_width(20)
        self.set_resizable(True)
        self.set_decorated(True)
        icon = self.get_pixbuf("authentication.png")
        if icon:
            self.set_icon(icon)
        add_close_accel(self, self.quit)
        self.connect("delete_event", self.quit)

        self.vbox = Gtk.VBox(False, 20)
        self.add(self.vbox)

        title_label = Gtk.Label(title)
        title_label.modify_font(Pango.FontDescription("sans 14"))
        self.vbox.add(title_label)

        info_label = Gtk.Label(info)
        info_label.modify_font(Pango.FontDescription("sans 12"))
        self.vbox.add(info_label)

        if self.timeout>0:
            self.timeout_label = Gtk.Label()
            self.update_timeout()
            self.vbox.add(self.timeout_label)
            GLib.timeout_add(1000, self.update_timeout)

        #buttons:
        al = Gtk.Alignment(xalign=1.0, yalign=0.5, xscale=0.0, yscale=0.0)
        al.set_padding(0, 0, 10, 10)
        hbox = Gtk.HBox(False, 10)
        al.add(hbox)
        hbox.add(self.btn("Cancel", Gtk.STOCK_NO, self.cancel))
        hbox.add(self.btn("Accept", Gtk.STOCK_OK, self.accept))
        self.vbox.add(al)

        register_os_signals(self.app_signal, "Authentication Dialog")
        self.show_all()

    def btn(self, label, stock_icon, callback):
        btn = Gtk.Button(label)
        settings = btn.get_settings()
        settings.set_property('gtk-button-images', True)
        btn.connect("clicked", callback)
        if stock_icon:
            image = Gtk.Image.new_from_stock(stock_icon, Gtk.IconSize.BUTTON)
            if image:
                btn.set_image(image)
        return btn

    def update_timeout(self):
        if self.timeout<=0:
            self.exit_code = 2
            self.quit()
            return False
        self.timeout_label.set_text("This request will timeout in %i seconds" % self.timeout)
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

    def do_quit(self):
        log("do_quit()")
        Gtk.main_quit()

    def app_signal(self, signum):
        self.exit_code = 128 + signum
        log("app_signal(%s) exit_code=%i", signum, self.exit_code)
        self.do_quit()


    def get_pixbuf(self, icon_name):
        icon_filename = os.path.join(get_icon_dir(), icon_name)
        if os.path.exists(icon_filename):
            try:
                return GdkPixbuf.Pixbuf.new_from_file(icon_filename)
            except Exception as e:
                log("pixbuf_new_from_file(%s) failed: %s", icon_filename, e)
        return None


def main():
    from xpra.platform import program_context
    with program_context("Session Access"):
        from xpra.platform.gui import init as gui_init
        gui_init()
        if len(sys.argv)<2:
            sys.stderr.write("usage: %s 'message' [timeout-in-seconds]\n" % sys.argv[0])
            sys.exit(4)
        info = sys.argv[1]
        if len(sys.argv)>=3:
            timeout = int(sys.argv[2])
        else:
            timeout = 600
        w = AuthDialog(info=info, timeout=timeout)
        Gtk.main()
        return w.exit_code


if __name__ == "__main__":
    r = main()
    sys.exit(r)
