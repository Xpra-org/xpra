# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2018-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import subprocess

from gi.repository import GLib, Pango, Gtk, Gdk, Gio

from xpra.gtk_common.gobject_compat import register_os_signals
from xpra.gtk_common.gtk_util import (
    add_close_accel,
    add_window_accel, imagebutton,
    get_icon_pixbuf,
    )
from xpra.gtk_common.start_gui import StartSession
from xpra.platform.paths import get_xpra_command
from xpra.os_util import OSX, WIN32, platform_name
from xpra.log import Logger
from xpra.gtk_common.about import about

log = Logger("client", "util")

try:
    from xpra import client
    has_client = bool(client)
except ImportError:
    has_client = False
try:
    from xpra.server import server_util
    has_server = bool(server_util)
except ImportError:
    has_server = False
try:
    from xpra.server import shadow
    has_shadow = bool(shadow)
except ImportError:
    has_shadow = False
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


class GUI(Gtk.Window):

    def __init__(self, title="Xpra"):
        self.exit_code = 0
        self.start_session = None
        Gtk.Window.__init__(self)

        hb = Gtk.HeaderBar()
        hb.set_show_close_button(True)
        hb.props.title = "Xpra"
        self.set_titlebar(hb)
        hb.add(self.button("About", "help-about", about))
        try:
            from xpra.client.gtk_base.toolbox import ToolboxGUI
        except ImportError:
            pass
        else:
            def show():
                w = None
                def hide(*_args):
                    w.hide()
                ToolboxGUI.quit = hide
                w = ToolboxGUI()
                w.show()
            hb.add(self.button("Toolbox", "applications-utilities", show))
            hb.show_all()

        self.set_title(title)
        self.set_border_width(10)
        self.set_resizable(True)
        self.set_decorated(True)
        self.set_position(Gtk.WindowPosition.CENTER)
        icon = get_icon_pixbuf("xpra.png")
        if icon:
            self.set_icon(icon)
        add_close_accel(self, self.quit)
        add_window_accel(self, 'F1', self.show_about)
        self.connect("delete_event", self.quit)
        self.set_wmclass("xpra-gui", "Xpra-GUI")

        self.vbox = Gtk.VBox(False, 10)
        self.add(self.vbox)
        #with most window managers,
        #the window's title bar already shows "Xpra"
        #title_label = Gtk.Label(title)
        #title_label.modify_font(pango.FontDescription("sans 14"))
        #self.vbox.add(title_label)
        self.widgets = []
        label_font = Pango.FontDescription("sans 16")
        if has_client:
            icon = get_icon_pixbuf("browse.png")
            self.browse_button = imagebutton("Browse", icon,
                                             "Browse and connect to local and mDNS sessions", clicked_callback=self.browse,
                                             icon_size=48, label_font=label_font)
            self.widgets.append(self.browse_button)
            icon = get_icon_pixbuf("connect.png")
            self.connect_button = imagebutton("Connect", icon,
                                              "Connect to an existing session\nover the network", clicked_callback=self.show_launcher,
                                              icon_size=48, label_font=label_font)
            self.widgets.append(self.connect_button)
        if has_server:
            icon = get_icon_pixbuf("server-connected.png")
            self.shadow_button = imagebutton("Shadow", icon,
                                             "Start a shadow server,\nmaking this desktop accessible to others\n(authentication required)", clicked_callback=self.start_shadow,
                                             icon_size=48, label_font=label_font)
            if not has_shadow:
                self.shadow_button.set_tooltip_text("This build of Xpra does not support starting sessions")
                self.shadow_button.set_sensitive(False)
            self.widgets.append(self.shadow_button)
            icon = get_icon_pixbuf("windows.png")
            self.start_button = imagebutton("Start", icon,
                                            "Start a session", clicked_callback=self.start,
                                            icon_size=48, label_font=label_font)
            #not all builds and platforms can start sessions:
            if OSX or WIN32:
                self.start_button.set_tooltip_text("Starting sessions is not supported on %s" % platform_name(sys.platform))
                self.start_button.set_sensitive(False)
            elif not has_server:
                self.start_button.set_tooltip_text("This build of Xpra does not support starting sessions")
                self.start_button.set_sensitive(False)
            self.widgets.append(self.start_button)
        assert len(self.widgets)%2==0
        table = Gtk.Table(len(self.widgets)//2, 2, True)
        for i, widget in enumerate(self.widgets):
            table.attach(widget, i%2, i%2+1, i//2, i//2+1, xpadding=10, ypadding=10)
        self.vbox.add(table)
        self.vbox.show_all()
        self.set_size_request(640, 100+100*len(self.widgets)//2)
        def focus_in(window, event):
            log("focus_in(%s, %s)", window, event)
        def focus_out(window, event):
            log("focus_out(%s, %s)", window, event)
            self.reset_cursors()
        self.connect("focus-in-event", focus_in)
        self.connect("focus-out-event", focus_out)

    def button(self, tooltip, icon_name, callback):
        button = Gtk.Button()
        icon = Gio.ThemedIcon(name=icon_name)
        image = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)
        button.add(image)
        button.set_tooltip_text(tooltip)
        def clicked(*_args):
            callback()
        button.connect("clicked", clicked)
        return button


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


    def reset_cursors(self):
        for widget in self.widgets:
            widget.get_window().set_cursor(None)

    def busy_cursor(self, widget):
        from xpra.gtk_common.cursor_names import cursor_types
        watch = cursor_types.get("WATCH")
        if watch:
            display = Gdk.Display.get_default()
            cursor = Gdk.Cursor.new_for_display(display, watch)
            widget.get_window().set_cursor(cursor)
            GLib.timeout_add(5*1000, self.reset_cursors)


    def show_about(self, *_args):
        about()

    def start_shadow(self, *_args):
        cmd = get_xpra_command()+["shadow"]
        proc = exec_command(cmd)
        if proc.poll() is None:
            self.busy_cursor(self.shadow_button)

    def browse(self, *_args):
        cmd = get_xpra_command()+["sessions"]
        proc = exec_command(cmd)
        if proc.poll() is None:
            self.busy_cursor(self.browse_button)

    def show_launcher(self, *_args):
        cmd = get_xpra_command()+["launcher"]
        proc = exec_command(cmd)
        if proc.poll() is None:
            self.busy_cursor(self.connect_button)

    def start(self, *_args):
        if not self.start_session:
            self.start_session = StartSession()
            self.start_session.do_quit = self.start_session.hide_window
        self.start_session.populate_menus()
        self.start_session.show()
        self.start_session.present()

    def open_file(self, filename):
        log("open_file(%s)", filename)
        self.exec_subcommand("launcher", filename)

    def open_url(self, url):
        log("open_url(%s)", url)
        self.exec_subcommand("attach", url)

    def exec_subcommand(self, subcommand, arg):
        log("exec_subcommand(%s, %s)", subcommand, arg)
        cmd = get_xpra_command()
        cmd.append(subcommand)
        cmd.append(arg)
        proc = exec_command(cmd)
        if proc.poll() is None:
            self.hide()
            def may_exit():
                if proc.poll() is None:
                    self.quit()
                else:
                    self.show()
            #don't ask me why,
            #but on macos we can get file descriptor errors
            #if we exit immediately after we spawn the attach command
            GLib.timeout_add(2000, may_exit)


def main(): # pragma: no cover
    from xpra.platform import program_context
    from xpra.log import enable_color
    from xpra.platform.gui import init, ready
    with program_context("xpra-gui", "Xpra GUI"):
        enable_color()
        init()
        gui = GUI()
        register_os_signals(gui.app_signal)
        ready()
        if OSX:
            from xpra.platform.darwin.gui import wait_for_open_handlers
            wait_for_open_handlers(gui.show, gui.open_file, gui.open_url)
        else:
            gui.show()
        Gtk.main()
        log("do_main() gui.exit_code=%i", gui.exit_code)
        return 0


if __name__ == "__main__":  # pragma: no cover
    r = main()
    sys.exit(r)
