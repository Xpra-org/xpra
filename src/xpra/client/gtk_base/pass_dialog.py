#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


import os.path
import sys
import signal

from xpra.gtk_common.gobject_compat import import_gtk, import_pango, import_glib

gtk = import_gtk()
glib = import_glib()
pango = import_pango()


from xpra.os_util import get_util_logger
from xpra.gtk_common.gtk_util import gtk_main, add_close_accel, pixbuf_new_from_file, window_defaults, \
                                    WIN_POS_CENTER, WINDOW_TOPLEVEL, is_gtk3
from xpra.platform.paths import get_icon_dir
log = get_util_logger()


class PasswordInputDialogWindow(object):

    def __init__(self, title="Title", prompt="", info=[], icon="", buttons=[]):
        if is_gtk3():
            self.window = gtk.Window(type=WINDOW_TOPLEVEL)
        else:
            self.window = gtk.Window(WINDOW_TOPLEVEL)
        window_defaults(self.window)
        self.window.set_position(WIN_POS_CENTER)
        self.window.connect("destroy", self.quit)
        self.window.set_default_size(400, 150)
        self.window.set_title(title)
        self.window.set_modal(True)

        if icon:
            icon_pixbuf = self.get_icon(icon)
            if icon_pixbuf:
                self.window.set_icon(icon_pixbuf)

        vbox = gtk.VBox(False, 0)
        vbox.set_spacing(10)

        def al(label, font="sans 14", xalign=0):
            l = gtk.Label(label)
            l.modify_font(pango.FontDescription(font))
            al = gtk.Alignment(xalign=xalign, yalign=0.5, xscale=0.0, yscale=0)
            al.add(l)
            vbox.add(al)

        #window title is visible so this would be redundant:
        #al(title, "sans 18", 0.5)
        al(prompt, "sans 14")
        self.password_input = gtk.Entry()
        self.password_input.set_max_length(255)
        self.password_input.set_width_chars(32)
        self.password_input.connect('activate', self.activate)
        self.password_input.set_visibility(False)
        vbox.add(self.password_input)

        # Buttons:
        self.exit_code = 0
        hbox = gtk.HBox(False, 0)
        al = gtk.Alignment(xalign=1, yalign=0.5, xscale=0, yscale=0)
        al.add(hbox)
        vbox.pack_start(al)
        for label, code, isdefault in [("Confirm", 0, True), ("Cancel", 1, False)]:
            b = self.btn(label,  code, isdefault)
            hbox.pack_start(b)

        add_close_accel(self.window, self.quit)
        vbox.show_all()
        self.window.add(vbox)

    def btn(self, label, code, isdefault=False):
        btn = gtk.Button(label)
        settings = btn.get_settings()
        settings.set_property('gtk-button-images', True)
        def btn_clicked(*_args):
            log("%s button clicked, returning %s", label, code)
            self.exit_code = code
            self.quit()
        btn.set_size_request(100, 48)
        btn.connect("clicked", btn_clicked)
        btn.set_can_focus(True)
        btn.set_can_default(isdefault)
        if isdefault:
            self.window.set_default(btn)
            self.window.set_focus(btn)
        return btn


    def show(self):
        log("show()")
        self.window.show_all()
        glib.idle_add(self.window.present)

    def destroy(self, *args):
        log("destroy%s", args)
        if self.window:
            self.window.destroy()
            self.window = None

    def run(self):
        log("run()")
        gtk_main()
        log("run() gtk_main done")
        return self.exit_code

    def quit(self, *args):
        log("quit%s", args)
        self.destroy()
        gtk.main_quit()


    def activate(self, *args):
        log("activate%s", args)
        sys.stdout.write(self.password_input.get_text())
        sys.stdout.flush()
        self.quit()

    def get_icon(self, icon_name):
        icon_filename = os.path.join(get_icon_dir(), icon_name)
        if os.path.exists(icon_filename):
            return pixbuf_new_from_file(icon_filename)
        return None


def show_pass_dialog(argv):
    from xpra.os_util import SIGNAMES
    from xpra.platform.gui import ready as gui_ready
    from xpra.gtk_common.quit import gtk_main_quit_on_fatal_exceptions_enable
    from xpra.platform.gui import init as gui_init

    gui_init()
    gtk_main_quit_on_fatal_exceptions_enable()

    log("show_pass_dialog(%s)", argv)
    def arg(n):
        if len(argv)<=n:
            return ""
        return argv[n].replace("\\n\\r", "\\n").replace("\\n", "\n")
    title = arg(0) or "Enter Password"
    prompt = arg(1)
    icon = arg(2)
    app = PasswordInputDialogWindow(title, prompt, icon)
    def app_signal(signum, _frame):
        print("")
        log.info("got signal %s", SIGNAMES.get(signum, signum))
        app.quit()
    signal.signal(signal.SIGINT, app_signal)
    signal.signal(signal.SIGTERM, app_signal)
    gui_ready()
    app.show()
    return app.run()
    

def main():
    from xpra.platform import program_context
    with program_context("Password-Input-Dialog", "Password Input Dialog"):
        if "-v" in sys.argv:
            from xpra.log import enable_debug_for
            enable_debug_for("util")

        try:
            return show_pass_dialog(sys.argv[1:])
        except KeyboardInterrupt:
            return 1


if __name__ == "__main__":
    v = main()
    sys.exit(v)
