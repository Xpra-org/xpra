# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2018-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path
import subprocess

from gi.repository import Pango, Gtk

from xpra.gtk_common.gobject_compat import register_os_signals
from xpra.gtk_common.gtk_util import (
    add_close_accel,
    scaled_image, get_icon_pixbuf,
    )
from xpra.platform.paths import get_xpra_command
from xpra.log import Logger

log = Logger("client", "util")

try:
    import xdg
except ImportError:
    xdg = None


def exec_command(cmd):
    env = os.environ.copy()
    env["XPRA_WAIT_FOR_INPUT"] = "0"
    proc = subprocess.Popen(cmd, env=env)
    log("exec_command(%s)=%s", cmd, proc)
    return proc


class StartSession(Gtk.Window):

    def __init__(self):
        self.exit_code = None
        Gtk.Window.__init__(self)
        self.set_border_width(20)
        self.set_title("Start Xpra Session")
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_size_request(640, 300)
        icon = get_icon_pixbuf("xpra.png")
        if icon:
            self.set_icon(icon)
        self.connect("delete-event", self.quit)
        add_close_accel(self, self.quit)

        vbox = Gtk.VBox(False, 0)
        vbox.set_spacing(0)

        # choose the session type:
        hbox = Gtk.HBox(True, 10)
        def ralx(btn, xalign=1):
            al = Gtk.Alignment(xalign=xalign, yalign=0.5, xscale=0.0, yscale=0)
            al.add(btn)
            hbox.add(al)
        self.seamless_btn = Gtk.RadioButton.new_with_label(None, "Seamless Session")
        self.seamless_btn.connect("toggled", self.mode_toggled)
        ralx(self.seamless_btn)
        self.desktop_btn = Gtk.RadioButton.new_with_label_from_widget(self.seamless_btn, "Desktop Session")
        self.desktop_btn.connect("toggled", self.mode_toggled)
        ralx(self.desktop_btn)
        self.shadow_btn = Gtk.RadioButton.new_with_label_from_widget(self.seamless_btn, "Shadow Session")
        self.shadow_btn.connect("toggled", self.mode_toggled)
        ralx(self.shadow_btn)
        self.seamless = True
        vbox.pack_start(hbox, False)

        options_box = Gtk.VBox(False, 10)
        vbox.pack_start(options_box, True, False, 20)
        # For Shadow mode only:
        self.display_box = Gtk.HBox(False, 20)
        options_box.pack_start(self.display_box, False, True, 20)
        self.display_label = Gtk.Label("Display:")
        self.display_entry = Gtk.Entry()
        self.display_entry.set_text("")
        self.display_entry.set_width_chars(10)
        self.display_entry.set_placeholder_text("optional")
        self.display_entry.set_max_length(10)
        self.display_box.pack_start(self.display_label, True)
        self.display_box.pack_start(self.display_entry, True, False)

        # Label:
        self.entry_label = Gtk.Label("Command to run:")
        self.entry_label.modify_font(Pango.FontDescription("sans 14"))
        self.entry_al = Gtk.Alignment(xalign=0, yalign=0.5, xscale=0.0, yscale=0)
        self.entry_al.add(self.entry_label)
        options_box.pack_start(self.entry_al, False)
        # input command directly as text (if pyxdg is not installed):
        self.entry = Gtk.Entry()
        self.entry.set_max_length(255)
        self.entry.set_width_chars(32)
        self.entry.connect('activate', self.run_command)
        options_box.pack_start(self.entry, False)

        # or use menus if we have xdg data:
        self.category_box = Gtk.HBox(False, 20)
        options_box.pack_start(self.category_box, False)
        self.category_label = Gtk.Label("Category:")
        self.category_combo = Gtk.ComboBoxText()
        self.category_box.add(self.category_label)
        self.category_box.add(self.category_combo)
        self.category_combo.connect("changed", self.category_changed)
        self.categories = {}

        self.command_box = Gtk.HBox(False, 20)
        options_box.pack_start(self.command_box, False)
        self.command_label = Gtk.Label("Command:")
        self.command_combo = Gtk.ComboBoxText()
        self.command_box.pack_start(self.command_label)
        self.command_box.pack_start(self.command_combo)
        self.command_combo.connect("changed", self.command_changed)
        self.commands = {}
        self.xsessions = None
        self.desktop_entry = None

        # start options:
        hbox = Gtk.HBox(False, 20)
        options_box.pack_start(hbox, False)
        self.attach_cb = Gtk.CheckButton()
        self.attach_cb.set_label("attach immediately")
        self.attach_cb.set_active(True)
        al = Gtk.Alignment(xalign=1, yalign=0.5, xscale=0.0, yscale=0)
        al.add(self.attach_cb)
        hbox.add(al)
        self.exit_with_children_cb = Gtk.CheckButton()
        self.exit_with_children_cb.set_label("exit with application")
        hbox.add(self.exit_with_children_cb)
        self.exit_with_children_cb.set_active(True)
        self.exit_with_client_cb = Gtk.CheckButton()
        self.exit_with_client_cb.set_label("exit with client")
        hbox.add(self.exit_with_client_cb)
        self.exit_with_client_cb.set_active(False)
        #maybe add:
        #clipboard, opengl, sharing?

        # Action buttons:
        hbox = Gtk.HBox(False, 20)
        vbox.pack_start(hbox, False, True, 20)
        def btn(label, tooltip, callback, icon_name=None):
            btn = Gtk.Button(label)
            btn.set_tooltip_text(tooltip)
            btn.connect("clicked", callback)
            icon = get_icon_pixbuf(icon_name)
            if icon:
                btn.set_image(scaled_image(icon, 24))
            hbox.pack_start(btn)
            return btn
        self.cancel_btn = btn("Cancel", "", self.quit, "quit.png")
        self.run_btn = btn("Start", "Start this command in an xpra session", self.run_command, "forward.png")
        self.run_btn.set_sensitive(False)

        vbox.show_all()
        self.add(vbox)


    def app_signal(self, signum):
        if self.exit_code is None:
            self.exit_code = 128 + signum
        log("app_signal(%s) exit_code=%i", signum, self.exit_code)
        self.quit()

    def quit(self, *args):
        log("quit%s", args)
        self.do_quit()

    def do_quit(self):
        log("do_quit()")
        Gtk.main_quit()


    def populate_menus(self):
        shadow_mode = self.shadow_btn.get_active()
        if shadow_mode:
            #only option we show is the optional display input
            self.display_box.show_all()
            self.entry_al.hide()
            self.entry.hide()
            self.category_box.hide()
            self.command_box.hide()
            self.exit_with_children_cb.hide()
        else:
            self.command_label.set_text("Command:" if self.seamless else "Desktop Environment:")
            self.display_box.hide()
            self.command_box.show_all()
            self.exit_with_children_cb.show()
            if xdg:
                #we have menus, so hide text input:
                self.entry_al.hide()
                self.entry.hide()
                if self.seamless:
                    self.category_box.show()
                    self.populate_category()
                else:
                    self.category_box.hide()
                    self.populate_command()
                return
            else:
                self.entry_al.show_all()


    def populate_category(self):
        self.categories = {}
        try:
            from xdg.Menu import parse, Menu
            menu = parse()
            for submenu in menu.getEntries():
                if isinstance(submenu, Menu) and submenu.Visible:
                    name = submenu.getName()
                    if self.categories.get(name) is None:
                        self.categories[name] = submenu
        except Exception:
            log("failed to parse menus", exc_info=True)
        model = self.category_combo.get_model()
        if model:
            model.clear()
        for name in sorted(self.categories.keys()):
            self.category_combo.append_text(name)
        if self.categories:
            self.category_combo.set_active(0)

    def category_changed(self, *args):
        category = self.category_combo.get_active_text()
        log("category_changed(%s) category=%s", args, category)
        self.commands = {}
        self.desktop_entry = None
        if category:
            from xdg.Menu import Menu, MenuEntry
            #find the matching submenu:
            submenu = self.categories[category]
            assert isinstance(submenu, Menu)
            for entry in submenu.getEntries():
                #can we have more than 2 levels of submenus?
                if isinstance(entry, MenuEntry):
                    name = entry.DesktopEntry.getName()
                    self.commands[name] = entry.DesktopEntry
        self.command_combo.get_model().clear()
        for name in sorted(self.commands.keys()):
            self.command_combo.append_text(name)
        if self.commands:
            self.command_combo.set_active(0)
        self.command_box.show()


    def populate_command(self):
        log("populate_command()")
        self.command_combo.get_model().clear()
        if self.xsessions is None:
            assert xdg
            from xdg.DesktopEntry import DesktopEntry
            xsessions_dir = "%s/share/xsessions" % sys.prefix
            self.xsessions = {}
            if os.path.exists(xsessions_dir):
                for f in os.listdir(xsessions_dir):
                    filename = os.path.join(xsessions_dir, f)
                    de = DesktopEntry(filename)
                    self.xsessions[de.getName()] = de
        log("populate_command() xsessions=%s", self.xsessions)
        for name in sorted(self.xsessions.keys()):
            self.command_combo.append_text(name)
        self.command_combo.set_active(0)

    def command_changed(self, *args):
        name = self.command_combo.get_active_text()
        log("command_changed(%s) command=%s", args, name)
        if name:
            if self.seamless:
                self.desktop_entry = self.commands[name]
            else:
                self.desktop_entry = self.xsessions[name]
            log("command_changed(%s) desktop_entry=%s", args, self.desktop_entry)
            self.run_btn.set_sensitive(True)
        else:
            self.desktop_entry = None
            self.run_btn.set_sensitive(False)


    def mode_toggled(self, *args):
        self.seamless = self.seamless_btn.get_active()
        log("mode_toggled(%s) seamless=%s", args, self.seamless)
        if self.shadow_btn.get_active():
            self.exit_with_client_cb.set_active(True)
        self.populate_menus()


    def hide_window(self, *args):
        log("hide_window%s", args)
        self.hide()
        return True


    def run_command(self, *_args):
        self.hide()
        if xdg:
            if self.desktop_entry.getTryExec():
                try:
                    command = self.desktop_entry.findTryExec()
                except Exception:
                    command = self.desktop_entry.getTryExec()
            else:
                command = self.desktop_entry.getExec()
        else:
            command = self.entry.get_text()
        cmd = get_xpra_command()
        shadow = self.shadow_btn.get_active()
        if self.seamless:
            cmd.append("start")
        elif shadow:
            cmd.append("shadow")
        else:
            cmd.append("start-desktop")
        ewc = self.exit_with_client_cb.get_active()
        cmd.append("--exit-with-client=%s" % ewc)
        if not shadow:
            ewc = self.exit_with_children_cb.get_active()
            cmd.append("--exit-with-children=%s" % ewc)
            if ewc:
                cmd.append("--start-child=%s" % command)
            else:
                cmd.append("--start=%s" % command)
        cmd.append("--attach=%s" % self.attach_cb.get_active())
        exec_command(cmd)


def main(): # pragma: no cover
    from xpra.platform import program_context
    from xpra.log import enable_color
    from xpra.platform.gui import init, ready
    with program_context("xpra-start-gui", "Xpra Start GUI"):
        enable_color()
        init()
        gui = StartSession()
        register_os_signals(gui.app_signal)
        ready()
        gui.populate_menus()
        gui.show()
        gui.present()
        Gtk.main()
        log("do_main() gui.exit_code=%i", gui.exit_code)
        return 0


if __name__ == "__main__":  # pragma: no cover
    r = main()
    sys.exit(r)
