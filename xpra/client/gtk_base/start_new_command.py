#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2014-2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


import os.path
import sys

from xpra.gtk_common.gtk_util import (
    gtk_main, add_close_accel, scaled_image, pixbuf_new_from_file,
    window_defaults, WIN_POS_CENTER,
    )
from xpra.gtk_common.gobject_compat import (
    import_gtk, import_gdk, import_gobject, import_pango, import_glib,
    register_os_signals,
    )
from xpra.platform.paths import get_icon_dir
from xpra.util import typedict
from xpra.log import Logger, enable_debug_for

log = Logger("exec")

glib = import_glib()
gtk = import_gtk()
gdk = import_gdk()
gobject = import_gobject()
pango = import_pango()


_instance = None
def getStartNewCommand(run_callback, can_share=False, xdg_menu=None):
    global _instance
    if _instance is None:
        _instance = StartNewCommand(run_callback, can_share, xdg_menu)
    return _instance


class StartNewCommand(object):

    def __init__(self, run_callback=None, can_share=False, xdg_menu=None):
        self.run_callback = run_callback
        self.xdg_menu = typedict(xdg_menu or {})
        self.window = gtk.Window()
        window_defaults(self.window)
        self.window.connect("delete-event", self.close)
        self.window.set_default_size(400, 150)
        self.window.set_title("Start New Command")

        icon_pixbuf = self.get_icon("forward.png")
        if icon_pixbuf:
            self.window.set_icon(icon_pixbuf)
        self.window.set_position(WIN_POS_CENTER)

        vbox = gtk.VBox(False, 0)
        vbox.set_spacing(0)

        self.entry = None
        if xdg_menu:
            # or use menus if we have xdg data:
            hbox = gtk.HBox(False, 20)
            vbox.add(hbox)
            hbox.add(gtk.Label("Category:"))
            self.category_combo = gtk.combo_box_new_text()
            hbox.add(self.category_combo)
            for name in sorted(xdg_menu.keys()):
                self.category_combo.append_text(name.decode("utf-8"))
            self.category_combo.set_active(0)
            self.category_combo.connect("changed", self.category_changed)

            hbox = gtk.HBox(False, 20)
            vbox.add(hbox)
            self.command_combo = gtk.combo_box_new_text()
            hbox.pack_start(gtk.Label("Command:"))
            hbox.pack_start(self.command_combo)
            self.command_combo.connect("changed", self.command_changed)
            #this will populate the command combo:
            self.category_changed()
        #always show the command as text so it can be edited:
        entry_label = gtk.Label("Command to run:")
        entry_label.modify_font(pango.FontDescription("sans 14"))
        entry_al = gtk.Alignment(xalign=0, yalign=0.5, xscale=0.0, yscale=0)
        entry_al.add(entry_label)
        vbox.add(entry_al)
        # Actual command:
        self.entry = gtk.Entry()
        self.entry.set_max_length(255)
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


    def category_changed(self, *args):
        category = self.category_combo.get_active_text().encode("utf-8")
        entries = typedict(self.xdg_menu.dictget(category, {})).dictget("Entries", {})
        log("category_changed(%s) category=%s, entries=%s", args, category, entries)
        self.command_combo.get_model().clear()
        for name in entries.keys():
            self.command_combo.append_text(name.decode("utf-8"))
        if entries:
            self.command_combo.set_active(0)

    def command_changed(self, *args):
        if not self.entry:
            return
        category = self.category_combo.get_active_text()
        entries = typedict(self.xdg_menu.dictget(category.encode("utf-8"), {})).dictget("Entries", {})
        command_name = self.command_combo.get_active_text()
        log("command_changed(%s) category=%s, entries=%s, command_name=%s", args, category, entries, command_name)
        command = ""
        if entries and command_name:
            command_props = typedict(entries).dictget(command_name.encode("utf-8"), {})
            log("command properties=%s", command_props)
            command = typedict(command_props).strget(b"command", "")
        self.entry.set_text(command)


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
        return True

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
        log("command=%s", command)
        if self.run_callback and command:
            self.run_callback(command, self.share is None or self.share.get_active())


def main():
    from xpra.platform.gui import init as gui_init, ready as gui_ready
    from xpra.platform import program_context
    gui_init()
    with program_context("Start-New-Command", "Start New Command"):
        #logging init:
        if "-v" in sys.argv:
            enable_debug_for("util")

        from xpra.gtk_common.quit import gtk_main_quit_on_fatal_exceptions_enable
        gtk_main_quit_on_fatal_exceptions_enable()

        app = StartNewCommand()
        app.hide = app.quit
        register_os_signals(app.quit)
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
