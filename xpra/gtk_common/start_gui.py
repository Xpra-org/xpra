# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2018-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path
import subprocess

from gi.repository import Gtk, Pango, GLib

from xpra.gtk_common.gobject_compat import register_os_signals
from xpra.gtk_common.gtk_util import (
    add_close_accel,
    get_icon_pixbuf,
    imagebutton,
    )
from xpra.os_util import OSX, WIN32, platform_name
from xpra.platform.paths import get_xpra_command
from xpra.log import Logger

log = Logger("client", "util")

try:
    import xdg
except ImportError:
    xdg = None

REQUIRE_COMMAND = False


def exec_command(cmd):
    env = os.environ.copy()
    env["XPRA_WAIT_FOR_INPUT"] = "0"
    env["XPRA_NOTTY"] = "1"
    proc = subprocess.Popen(cmd, env=env)
    log("exec_command(%s)=%s", cmd, proc)
    return proc


def xal(widget, xalign=1):
    al = Gtk.Alignment(xalign=xalign, yalign=0.5, xscale=0.0, yscale=0)
    al.add(widget)
    return al

def sf(w, font="sans 14"):
    w.modify_font(Pango.FontDescription(font))
    return w

def l(label):
    widget = Gtk.Label(label)
    return sf(widget)

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
        vbox.set_spacing(10)

        # choose the session type:
        hbox = Gtk.HBox(True, 40)
        def rb(sibling=None, label="", cb=None, tooltip_text=None):
            btn = Gtk.RadioButton.new_with_label_from_widget(sibling, label)
            if cb:
                btn.connect("toggled", cb)
            if tooltip_text:
                btn.set_tooltip_text(tooltip_text)
            sf(btn, "sans 16")
            hbox.add(btn)
            return btn
        self.seamless_btn = rb(None, "Seamless Session", self.session_toggled,
                               "Forward an application window(s) individually, seamlessly")
        self.desktop_btn = rb(self.seamless_btn, "Desktop Session", self.session_toggled,
                              "Forward a full desktop environment, contained in a window")
        self.shadow_btn = rb(self.seamless_btn, "Shadow Session", self.session_toggled,
                             "Forward an existing desktop session, shown in a window")
        vbox.pack_start(hbox, False)

        vbox.pack_start(Gtk.HSeparator(), True, False)

        options_box = Gtk.VBox(False, 10)
        vbox.pack_start(options_box, True, False, 20)
        # select host:
        host_box = Gtk.HBox(True, 20)
        options_box.pack_start(host_box, False)
        self.host_label = l("Host:")
        hbox = Gtk.HBox(True, 0)
        host_box.pack_start(self.host_label, True)
        host_box.pack_start(hbox, True, True)
        self.localhost_btn = rb(None, "Local System", self.host_toggled)
        self.remote_btn = rb(self.localhost_btn, "Remote")
        self.remote_btn.set_tooltip_text("Start sessions on a remote system")
        self.address_box = Gtk.HBox(False, 0)
        options_box.pack_start(xal(self.address_box), True, True)
        self.mode_combo = sf(Gtk.ComboBoxText())
        self.address_box.pack_start(xal(self.mode_combo), False)
        for mode in ("SSH", "TCP", "SSL", "WS", "WSS"):
            self.mode_combo.append_text(mode)
        self.mode_combo.set_active(0)
        self.mode_combo.connect("changed", self.mode_changed)
        self.username_entry = sf(Gtk.Entry())
        self.username_entry.set_width_chars(12)
        self.username_entry.set_placeholder_text("Username")
        self.username_entry.set_max_length(255)
        self.address_box.pack_start(xal(self.username_entry), False)
        self.address_box.pack_start(l("@"), False)
        self.host_entry = sf(Gtk.Entry())
        self.host_entry.set_width_chars(24)
        self.host_entry.set_placeholder_text("Hostname or IP address")
        self.host_entry.set_max_length(255)
        self.address_box.pack_start(xal(self.host_entry), False)
        self.address_box.pack_start(Gtk.Label(":"), False)
        self.port_entry = sf(Gtk.Entry())
        self.port_entry.set_text("22")
        self.port_entry.set_width_chars(5)
        self.port_entry.set_placeholder_text("Port")
        self.port_entry.set_max_length(5)
        self.address_box.pack_start(xal(self.port_entry, 0), False)

        # For Shadow mode only:
        self.display_box = Gtk.HBox(True, 20)
        options_box.pack_start(self.display_box, False, True, 20)
        self.display_label = l("Display:")
        self.display_entry = sf(Gtk.Entry())
        self.display_entry.connect('changed', self.display_changed)
        self.display_entry.set_width_chars(10)
        self.display_entry.set_placeholder_text("optional")
        self.display_entry.set_max_length(10)
        self.display_entry.set_tooltip_text("To use a specific X11 display number")
        self.display_box.pack_start(self.display_label, True)
        self.display_box.pack_start(self.display_entry, True, False)

        # Label:
        self.entry_box = Gtk.HBox(True, 20)
        options_box.pack_start(self.entry_box, False, True, 20)
        self.entry_label = l("Command:")
        self.entry = sf(Gtk.Entry())
        self.entry.set_max_length(255)
        self.entry.set_width_chars(32)
        #self.entry.connect('activate', self.run_command)
        self.entry.connect('changed', self.entry_changed)
        self.entry_box.pack_start(self.entry_label, True)
        self.entry_box.pack_start(self.entry, True, False)

        # or use menus if we have xdg data:
        self.category_box = Gtk.HBox(True, 20)
        options_box.pack_start(self.category_box, False)
        self.category_label = l("Category:")
        self.category_combo = sf(Gtk.ComboBoxText())
        self.category_box.pack_start(self.category_label, True)
        self.category_box.pack_start(self.category_combo, True, True)
        self.category_combo.connect("changed", self.category_changed)
        self.categories = {}

        self.command_box = Gtk.HBox(True, 20)
        options_box.pack_start(self.command_box, False)
        self.command_label = l("Command:")
        self.command_combo = sf(Gtk.ComboBoxText())
        self.command_box.pack_start(self.command_label, True)
        self.command_box.pack_start(self.command_combo, True, True)
        self.command_combo.connect("changed", self.command_changed)
        self.commands = {}
        self.xsessions = None
        self.desktop_entry = None

        # start options:
        hbox = Gtk.HBox(False, 20)
        options_box.pack_start(hbox, False)
        self.exit_with_children_cb = sf(Gtk.CheckButton())
        self.exit_with_children_cb.set_label("exit with application")
        hbox.add(xal(self.exit_with_children_cb, 0.5))
        self.exit_with_children_cb.set_active(True)
        self.exit_with_client_cb = sf(Gtk.CheckButton())
        self.exit_with_client_cb.set_label("exit with client")
        hbox.add(xal(self.exit_with_client_cb, 0.5))
        self.exit_with_client_cb.set_active(False)
        #maybe add:
        #clipboard, opengl, sharing?

        # Action buttons:
        hbox = Gtk.HBox(False, 20)
        vbox.pack_start(hbox, False, True, 20)
        def btn(label, tooltip, callback, default=False):
            btn = imagebutton(label, tooltip=tooltip, clicked_callback=callback, icon_size=32,
                default=default, label_font=Pango.FontDescription("sans 16"))
            hbox.pack_start(btn)
            return btn
        self.cancel_btn = btn("Cancel", "",
                              self.quit)
        self.run_btn = btn("Start", "Start the xpra session",
                           self.run_command)
        self.runattach_btn = btn("Start & Attach", "Start the xpra session and attach to it",
                                 self.runattach_command, True)
        self.runattach_btn.set_sensitive(False)

        vbox.show_all()
        self.add(vbox)


    def app_signal(self, signum):
        if self.exit_code is None:
            self.exit_code = 128 + signum
        log("app_signal(%s) exit_code=%i", signum, self.exit_code)
        self.quit()

    def quit(self, *args):
        log("quit%s", args)
        if self.exit_code is None:
            self.exit_code = 0
        self.do_quit()

    def do_quit(self):
        log("do_quit()")
        Gtk.main_quit()


    def populate_menus(self):
        localhost = self.localhost_btn.get_active()
        if (OSX or WIN32) and localhost:
            self.shadow_btn.set_active(True)
            self.display_box.hide()
        else:
            self.display_box.show()
        shadow_mode = self.shadow_btn.get_active()
        seamless = self.seamless_btn.get_active()
        if localhost:
            self.address_box.hide()
        else:
            self.address_box.show_all()
        if shadow_mode:
            #only option we show is the optional display input
            self.entry_box.hide()
            self.category_box.hide()
            self.command_box.hide()
            self.exit_with_children_cb.hide()
        else:
            self.exit_with_children_cb.show()
            if xdg and localhost:
                #we have the xdg menus and the server is local, so we can use them:
                self.entry_box.hide()
                self.command_label.set_text("Command:" if seamless else "Desktop Environment:")
                self.command_box.show_all()
                if seamless:
                    self.category_box.show()
                    self.populate_category()
                else:
                    self.category_box.hide()
                    self.populate_command()
                self.exit_with_children_cb.set_sensitive(True)
            else:
                #remote server (or missing xdg data)
                self.command_box.hide()
                self.category_box.hide()
                self.entry_label.set_text("Command:" if seamless else "Desktop Environment:")
                self.entry_box.show_all()
                self.exit_with_children_cb.set_sensitive(bool(self.entry.get_text()))


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
        if self.shadow_btn.get_active():
            return
        name = self.command_combo.get_active_text()
        log("command_changed(%s) command=%s", args, name)
        if name:
            seamless = self.seamless_btn.get_active()
            if seamless:
                self.desktop_entry = self.commands[name]
            else:
                self.desktop_entry = self.xsessions[name]
            log("command_changed(%s) desktop_entry=%s", args, self.desktop_entry)
        else:
            self.desktop_entry = None
        self.run_btn.set_sensitive(not REQUIRE_COMMAND or bool(name))
        self.runattach_btn.set_sensitive(not REQUIRE_COMMAND or bool(name))

    def entry_changed(self, *args):
        if self.shadow_btn.get_active():
            return
        text = self.entry.get_text()
        log("entry_changed(%s) entry=%s", args, text)
        self.exit_with_children_cb.set_sensitive(bool(text))
        self.run_btn.set_sensitive(not REQUIRE_COMMAND or bool(text))
        self.runattach_btn.set_sensitive(not REQUIRE_COMMAND or bool(text))

    def get_default_port(self, mode):
        return {
            "SSH" : 22,
            }.get(mode, 14500)


    def mode_changed(self, *args):
        log("mode_changed(%s)", args)
        mode = self.mode_combo.get_active_text()
        self.port_entry.set_text(str(self.get_default_port(mode)))

    def session_toggled(self, *args):
        localhost = self.localhost_btn.get_active()
        log("session_toggled(%s) localhost=%s", args, localhost)
        shadow = self.shadow_btn.get_active()
        local_shadow_only = WIN32 or OSX
        if shadow:
            self.exit_with_client_cb.set_active(True)
        elif local_shadow_only and localhost:
            #can only do shadow on localhost, so switch to remote:
            self.remote_btn.set_active(True)
        can_use_localhost = shadow or not local_shadow_only
        self.localhost_btn.set_sensitive(can_use_localhost)
        self.localhost_btn.set_tooltip_text("Start sessions on the local system" if can_use_localhost else
                                            "Cannot start local desktop or seamless sessions on %s" % platform_name())
        self.display_changed()
        self.populate_menus()
        self.entry_changed()

    def display_changed(self, *args):
        display = self.display_entry.get_text().lstrip(":")
        localhost = self.localhost_btn.get_active()
        shadow = self.shadow_btn.get_active()
        log("display_changed(%s) display=%s, localhost=%s, shadow=%s", args, display, localhost, shadow)
        ra_label = "Start the xpra session and attach to it"
        self.runattach_btn.set_sensitive(True)
        if shadow and localhost:
            if WIN32 or OSX or (not display or os.environ.get("DISPLAY", "").lstrip(":")==display):
                ra_label = "Cannot attach this desktop session to itself"
                self.runattach_btn.set_sensitive(False)
        self.runattach_btn.set_tooltip_text(ra_label)

    def host_toggled(self, *args):
        log("host_toggled(%s)", args)
        self.display_changed()
        self.populate_menus()
        self.entry_changed()


    def hide_window(self, *args):
        log("hide_window%s", args)
        self.hide()
        return True


    def run_command(self, *_args):
        self.do_run()

    def runattach_command(self, *_args):
        self.do_run(True)

    def do_run(self, attach=False):
        self.hide()
        cmd = self.get_run_command(attach)
        proc = exec_command(cmd)
        if proc:
            from xpra.make_thread import start_thread
            start_thread(self.wait_for_subprocess, "wait-%i" % proc.pid, daemon=True, args=(proc,))

    def wait_for_subprocess(self, proc):
        proc.wait()
        log("return code: %s", proc.returncode)
        GLib.idle_add(self.show)

    def get_run_command(self, attach=False):
        localhost = self.localhost_btn.get_active()
        if xdg and localhost:
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
        seamless = self.seamless_btn.get_active()
        if seamless:
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
        cmd.append("--attach=%s" % attach)
        localhost = self.localhost_btn.get_active()
        display = self.display_entry.get_text().lstrip(":")
        if localhost:
            uri = ":"+display if display else ""
        else:
            mode = self.mode_combo.get_active_text()
            uri = "%s://" % mode.lower()
            username = self.username_entry.get_text()
            if username:
                uri += "%s@" % username
            host = self.host_entry.get_text()
            if host:
                uri += host
            port = self.port_entry.get_text()
            if port!=self.get_default_port(mode):
                uri += ":%s" % port
            uri += "/"
            if display:
                uri += display
        if uri:
            cmd.append(uri)
        return cmd


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
        log("do_main() gui.exit_code=%s", gui.exit_code)
        return gui.exit_code


if __name__ == "__main__":  # pragma: no cover
    r = main()
    sys.exit(r)
