# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


import os.path
import sys

from xpra.log import Logger
log = Logger("util")

from xpra.gtk_common.gtk_util import add_close_accel, pixbuf_new_from_file, gtk_main, image_new_from_stock, ICON_SIZE_BUTTON
from xpra.platform.paths import get_icon_dir
from xpra.gtk_common.gobject_compat import import_gtk, import_pango, import_glib
gtk = import_gtk()
pango = import_pango()
glib = import_glib()


class AuthDialog(gtk.Window):

    def __init__(self, title="Session Access Request", info="unknown user from unknown location", timeout=600):
        gtk.Window.__init__(self)
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

        self.vbox = gtk.VBox(False, 20)
        self.add(self.vbox)

        title_label = gtk.Label(title)
        title_label.modify_font(pango.FontDescription("sans 14"))
        self.vbox.add(title_label)

        info_label = gtk.Label(info)
        info_label.modify_font(pango.FontDescription("sans 12"))
        self.vbox.add(info_label)

        if self.timeout>0:
            self.timeout_label = gtk.Label()
            self.update_timeout()
            self.vbox.add(self.timeout_label)
            glib.timeout_add(1000, self.update_timeout)

        #buttons:
        al = gtk.Alignment(xalign=1.0, yalign=0.5, xscale=0.0, yscale=0.0)
        al.set_padding(0, 0, 10, 10)
        hbox = gtk.HBox(False, 10)
        al.add(hbox)
        hbox.add(self.btn("Cancel", gtk.STOCK_NO, self.cancel))
        hbox.add(self.btn("Accept", gtk.STOCK_OK, self.accept))
        self.vbox.add(al)

        import signal
        signal.signal(signal.SIGINT, self.app_signal)
        signal.signal(signal.SIGTERM, self.app_signal)
        self.show_all()

    def btn(self, label, stock_icon, callback):
        btn = gtk.Button(label)
        settings = btn.get_settings()
        settings.set_property('gtk-button-images', True)
        btn.connect("clicked", callback)
        if stock_icon:
            image = image_new_from_stock(stock_icon, ICON_SIZE_BUTTON)
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

    def cancel(self, btn):
        self.exit_code = 3
        self.quit()

    def accept(self, btn):
        self.exit_code = 0
        self.quit()

    def quit(self, *args):
        log("quit%s", args)
        self.do_quit()

    def do_quit(self):
        log("do_quit()")
        gtk.main_quit()

    def app_signal(self, signum, _frame):
        self.exit_code = 128 + signum
        log("app_signal(%s, %s) exit_code=%i", signum, _frame, self.exit_code)
        self.do_quit()


    def get_pixbuf(self, icon_name):
        icon_filename = os.path.join(get_icon_dir(), icon_name)
        if os.path.exists(icon_filename):
            return pixbuf_new_from_file(icon_filename)
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
        gtk_main()
        return w.exit_code


if __name__ == "__main__":
    r = main()
    sys.exit(r)
