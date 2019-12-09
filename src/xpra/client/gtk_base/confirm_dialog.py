#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


import os.path
import sys

from xpra.gtk_common.gobject_compat import (
    import_gtk, import_pango, import_glib,
    register_os_signals,
    )
from xpra.gtk_common.gtk_util import (
    gtk_main, add_close_accel, scaled_image, pixbuf_new_from_file,
    window_defaults, color_parse, is_gtk3,
    WIN_POS_CENTER, WINDOW_POPUP, STATE_NORMAL,
    )
from xpra.platform.gui import force_focus
from xpra.platform.paths import get_icon_dir
from xpra.os_util import get_util_logger

log = get_util_logger()

gtk = import_gtk()
glib = import_glib()
pango = import_pango()


class ConfirmDialogWindow(object):

    def __init__(self, title="Title", prompt="", info=(), icon="", buttons=()):
        if is_gtk3():
            self.window = gtk.Window(type=WINDOW_POPUP)
        else:
            self.window = gtk.Window(WINDOW_POPUP)
        window_defaults(self.window)
        self.window.set_position(WIN_POS_CENTER)
        self.window.connect("delete-event", self.quit)
        self.window.set_default_size(400, 150)
        self.window.set_title(title)
        #self.window.set_modal(True)

        if icon:
            icon_pixbuf = self.get_icon(icon)
            if icon_pixbuf:
                self.window.set_icon(icon_pixbuf)

        vbox = gtk.VBox(False, 0)
        vbox.set_spacing(10)

        def al(label, font="sans 14", xalign=0):
            l = gtk.Label(label)
            l.modify_font(pango.FontDescription(font))
            if label.startswith("WARNING"):
                red = color_parse("red")
                l.modify_fg(STATE_NORMAL, red)
            al = gtk.Alignment(xalign=xalign, yalign=0.5, xscale=0.0, yscale=0)
            al.add(l)
            vbox.add(al)

        al(title, "sans 18", 0.5)
        al(info, "sans 14")
        al(prompt, "sans 14")

        # Buttons:
        self.exit_code = 0
        if buttons:
            hbox = gtk.HBox(False, 0)
            al = gtk.Alignment(xalign=1, yalign=0.5, xscale=0, yscale=0)
            al.add(hbox)
            vbox.pack_start(al)
            for label, code in buttons:
                b = self.btn(label,  "", code)
                hbox.pack_start(b)

        add_close_accel(self.window, self.quit)
        vbox.show_all()
        self.window.add(vbox)

    def btn(self, label, tooltip, code, icon_name=None):
        btn = gtk.Button(label)
        settings = btn.get_settings()
        settings.set_property('gtk-button-images', True)
        if tooltip:
            btn.set_tooltip_text(tooltip)
        def btn_clicked(*_args):
            log("%s button clicked, returning %s", label, code)
            self.exit_code = code
            self.quit()
        btn.set_size_request(100, 48)
        btn.connect("clicked", btn_clicked)
        btn.set_can_focus(True)
        isdefault = label[:1].upper()!=label[:1]
        btn.set_can_default(isdefault)
        if isdefault:
            self.window.set_default(btn)
            self.window.set_focus(btn)
        if icon_name:
            icon = self.get_icon(icon_name)
            if icon:
                btn.set_image(scaled_image(icon, 24))
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
        return True


    def get_icon(self, icon_name):
        icon_filename = os.path.join(get_icon_dir(), icon_name)
        if os.path.exists(icon_filename):
            return pixbuf_new_from_file(icon_filename)
        return None


def show_confirm_dialog(argv):
    from xpra.platform.gui import ready as gui_ready
    from xpra.gtk_common.quit import gtk_main_quit_on_fatal_exceptions_enable
    from xpra.platform.gui import init as gui_init

    gui_init()
    gtk_main_quit_on_fatal_exceptions_enable()

    log("show_confirm_dialog(%s)", argv)
    def arg(n):
        if len(argv)<=n:
            return ""
        return argv[n].replace("\\n\\r", "\\n").replace("\\n", "\n")
    title = arg(0) or "Confirm Key"
    prompt = arg(1)
    info = arg(2)
    icon = arg(3)
    buttons = []
    n = 4
    while len(argv)>(n+1):
        label = arg(n)
        try:
            code = int(arg(n+1))
        except ValueError as e:
            log.error("Error: confirm dialog cannot parse code '%s': %s", arg(n+1), e)
            return 1
        buttons.append((label, code))
        n += 2
    app = ConfirmDialogWindow(title, prompt, info, icon, buttons)
    register_os_signals(app.quit)
    gui_ready()
    force_focus()
    app.show()
    return app.run()


def main():
    from xpra.platform import program_context
    with program_context("Confirm-Dialog", "Confirm Dialog"):
        #logging init:
        if "-v" in sys.argv:
            from xpra.log import enable_debug_for
            enable_debug_for("util")

        try:
            return show_confirm_dialog(sys.argv[1:])
        except KeyboardInterrupt:
            return 1


if __name__ == "__main__":
    v = main()
    sys.exit(v)
