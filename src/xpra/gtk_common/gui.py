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
from xpra.gtk_common.gtk_util import gtk_main, add_close_accel, pixbuf_new_from_file, add_window_accel, imagebutton, window_defaults, scaled_image, WIN_POS_CENTER
from xpra.log import Logger
log = Logger("client", "util")


try:
    from xpra import client
    has_client = bool(client)
except ImportError:
    has_client = False
try:
    from xpra import server
    has_server = bool(server)
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
    proc = subprocess.Popen(cmd)
    log("exec_command(%s)=%s", cmd, proc)

def get_pixbuf(icon_name):
    icon_filename = os.path.join(get_icon_dir(), icon_name)
    if os.path.exists(icon_filename):
        return pixbuf_new_from_file(icon_filename)
    return None


class GUI(gtk.Window):

    def __init__(self, title="Xpra"):
        self.exit_code = 0
        self.start_session = None
        gtk.Window.__init__(self)
        self.set_title(title)
        self.set_border_width(10)
        self.set_resizable(True)
        self.set_decorated(True)
        self.set_position(WIN_POS_CENTER)
        self.set_size_request(640, 300)
        icon = get_pixbuf("xpra")
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
        widgets = []
        label_font = pango.FontDescription("sans 16")
        if has_client:
            icon = get_pixbuf("browse.png")
            self.browse_button = imagebutton("Browse", icon, "Browse and connect to local sessions", clicked_callback=self.browse, icon_size=48, label_font=label_font)
            widgets.append(self.browse_button)
            icon = get_pixbuf("connect.png")
            self.connect_button = imagebutton("Connect", icon, "Connect to a session", clicked_callback=self.show_launcher, icon_size=48, label_font=label_font)
            widgets.append(self.connect_button)
        if has_server:
            icon = get_pixbuf("server-connected.png")
            self.shadow_button = imagebutton("Shadow", icon, "Start a shadow server", clicked_callback=self.start_shadow, icon_size=48, label_font=label_font)
            if not has_shadow:
                self.shadow_button.set_tooltip_text("This build of Xpra does not support starting sessions")
                self.shadow_button.set_sensitive(False)
            widgets.append(self.shadow_button)
            icon = get_pixbuf("windows.png")
            self.start_button = imagebutton("Start", icon, "Start a session", clicked_callback=self.start, icon_size=48, label_font=label_font)
            #not all builds and platforms can start sessions:
            if OSX or WIN32:
                self.start_button.set_tooltip_text("Starting sessions is not supported on %s" % sys.platform)
                self.start_button.set_sensitive(False)
            elif not has_server:
                self.start_button.set_tooltip_text("This build of Xpra does not support starting sessions")
                self.start_button.set_sensitive(False)
            widgets.append(self.start_button)
        assert len(widgets)%2==0
        table = gtk.Table(2, len(widgets)//2, True)
        for i, widget in enumerate(widgets):
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


    def show_about(self, *_args):
        from xpra.gtk_common.about import about
        about()


    def start_shadow(self, *_args):
        cmd = get_xpra_command()+["shadow"]
        exec_command(cmd)

    def browse(self, *_args):
        subcommand = "mdns-gui"
        try:
            from xpra.net import mdns
            assert mdns
        except ImportError:
            subcommand = "sessions"
        cmd = get_xpra_command()+[subcommand]
        exec_command(cmd)

    def show_launcher(self, *_args):
        cmd = get_xpra_command()+["launcher"]
        exec_command(cmd)

    def start(self, *args):
        if not self.start_session:
            self.start_session = StartSession()
        self.start_session.show()
        self.start_session.present()


class StartSession(gtk.Window):

    def __init__(self):
        assert not WIN32 and not OSX
        gtk.Window.__init__(self)
        window_defaults(self)
        self.set_title("Start Xpra Session")
        self.set_position(WIN_POS_CENTER)
        self.set_size_request(640, 300)
        icon = get_pixbuf("xpra")
        if icon:
            self.set_icon(icon)
        self.connect("destroy", self.close)
        add_close_accel(self, self.close)

        vbox = gtk.VBox(False, 0)
        vbox.set_spacing(0)

        hbox = gtk.HBox(True, 10)
        self.seamless_btn = gtk.RadioButton(None, "Seamless Session")
        self.seamless_btn.connect("toggled", self.seamless_toggled)
        al = gtk.Alignment(xalign=1, yalign=0.5, xscale=0.0, yscale=0)
        al.add(self.seamless_btn)
        hbox.add(al)
        self.desktop_btn = gtk.RadioButton(self.seamless_btn, "Desktop Session")
        #since they're radio buttons, both get toggled,
        #so no need to connect to both signals:
        #self.desktop.connect("toggled", self.desktop_toggled)
        hbox.add(self.desktop_btn)
        self.seamless = True
        vbox.add(hbox)

        # Label:
        self.entry_label = gtk.Label("Command to run:")
        self.entry_label.modify_font(pango.FontDescription("sans 14"))
        self.entry_al = gtk.Alignment(xalign=0, yalign=0.5, xscale=0.0, yscale=0)
        self.entry_al.add(self.entry_label)
        vbox.add(self.entry_al)

        # input command directly as text (if pyxdg is not installed):
        self.entry = gtk.Entry()
        self.entry.set_max_length(255)
        self.entry.set_width_chars(32)
        self.entry.connect('activate', self.run_command)
        vbox.add(self.entry)

        # or use menus if we have xdg data:
        hbox = gtk.HBox(False, 20)
        vbox.add(hbox)
        self.category_box = hbox
        self.category_label = gtk.Label("Category:")
        self.category_combo = gtk.combo_box_new_text()
        hbox.add(self.category_label)
        hbox.add(self.category_combo)
        self.category_combo.connect("changed", self.category_changed)
        self.categories = {}

        hbox = gtk.HBox(False, 20)
        vbox.add(hbox)
        self.command_box = hbox
        self.command_label = gtk.Label("Command:")
        self.command_combo = gtk.combo_box_new_text()
        hbox.pack_start(self.command_label)
        hbox.pack_start(self.command_combo)
        self.command_combo.connect("changed", self.command_changed)
        self.commands = {}
        self.xsessions = None
        self.desktop_entry = None

        # start options:
        hbox = gtk.HBox(False, 20)
        vbox.add(hbox)
        self.attach_cb = gtk.CheckButton()
        self.attach_cb.set_label("attach immediately")
        self.attach_cb.set_active(True)
        al = gtk.Alignment(xalign=1, yalign=0.5, xscale=0.0, yscale=0)
        al.add(self.attach_cb)
        hbox.add(al)
        self.exit_with_children_cb = gtk.CheckButton()
        self.exit_with_children_cb.set_label("exit with children")
        hbox.add(self.exit_with_children_cb)
        self.exit_with_children_cb.set_active(True)
        #maybe add:
        #clipboard, opengl, sharing?

        # Action buttons:
        hbox = gtk.HBox(False, 20)
        vbox.add(hbox)
        def btn(label, tooltip, callback, icon_name=None):
            btn = gtk.Button(label)
            btn.set_tooltip_text(tooltip)
            btn.connect("clicked", callback)
            if icon_name:
                icon = get_pixbuf(icon_name)
                if icon:
                    btn.set_image(scaled_image(icon, 24))
            hbox.pack_start(btn)
            return btn
        self.cancel_btn = btn("Cancel", "", self.close, "quit.png")
        self.run_btn = btn("Start", "Start this command in an xpra session", self.run_command, "forward.png")
        self.run_btn.set_sensitive(False)

        vbox.show_all()
        self.add(vbox)


    def show(self):
        gtk.Window.show(self)
        self.populate_menus()


    def populate_menus(self):
        if xdg:
            self.entry_al.hide()
            self.entry.hide()
            if self.seamless:
                self.category_box.show()
                self.populate_category()
            else:
                self.category_box.hide()
                self.populate_command()
            return
        self.entry_al.show()
        self.entry.show()
        self.category_box.hide()
        self.command_box.hide()


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
        self.category_combo.get_model().clear()
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
                #TODO: can we have more than 2 levels of submenus?
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
            

    def seamless_toggled(self, *args):
        self.seamless = self.seamless_btn.get_active()
        log("seamless_toggled(%s) seamless=%s", args, self.seamless)
        self.populate_menus()


    def close(self, *args):
        log("close%s", args)
        self.hide()


    def run_command(self, *_args):
        self.hide()
        if xdg:
            if self.desktop_entry.getTryExec():
                command = self.desktop_entry.findTryExec()
            else:
                command = self.desktop_entry.getExec()
        else:
            command = self.entry.get_text()
        cmd = get_xpra_command()
        if self.seamless:
            cmd.append("start")
        else:
            cmd.append("start-desktop")
        ewc = self.exit_with_children_cb.get_active()
        cmd.append("--attach=%s" % self.attach_cb.get_active())
        cmd.append("--exit-with-children=%s" % ewc)
        if ewc:
            cmd.append("--start-child=%s" % command)
        else:
            cmd.append("--start=%s" % command)
        exec_command(cmd)


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
