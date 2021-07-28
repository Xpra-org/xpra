# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2018-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import time
import os.path
import subprocess

from gi.repository import Gtk, Gdk, Pango, GLib

from xpra.gtk_common.gobject_compat import register_os_signals
from xpra.gtk_common.gtk_util import (
    add_close_accel,
    get_icon_pixbuf,
    imagebutton,
    TableBuilder,
    )
from xpra.util import repr_ellipsized
from xpra.os_util import POSIX, OSX, WIN32, is_Wayland, platform_name
from xpra.simple_stats import std_unit_dec
from xpra.scripts.config import (
    get_defaults, parse_bool,
    OPTION_TYPES, FALSE_OPTIONS, TRUE_OPTIONS,
    )
from xpra.client.gtk_base.menu_helper import (
    BANDWIDTH_MENU_OPTIONS,
    )
from xpra.make_thread import start_thread
from xpra.platform.paths import get_xpra_command
from xpra.log import Logger

log = Logger("client", "util")

SCREEN_SIZES = os.environ.get("XPRA_SCREEN_SIZES", "1024x768,1600x1200,1920x1080,2560x1600,3840x2160").split(",")

try:
    import xdg
except ImportError:
    xdg = None

REQUIRE_COMMAND = False

UNSET = object()


def exec_command(cmd):
    env = os.environ.copy()
    env["XPRA_WAIT_FOR_INPUT"] = "0"
    env["XPRA_NOTTY"] = "1"
    proc = subprocess.Popen(cmd, env=env)
    log("exec_command(%s)=%s", cmd, proc)
    return proc


def xal(widget, xalign=1):
    al = Gtk.Alignment(xalign=xalign, yalign=0.5, xscale=0, yscale=0)
    al.add(widget)
    return al

def sf(w, font="sans 14"):
    w.modify_font(Pango.FontDescription(font))
    return w

def l(label):
    widget = Gtk.Label(label)
    return sf(widget)


def link_btn(link, label=None, icon_name="question.png"):
    def open_link():
        import webbrowser
        webbrowser.open(link)
    def help_clicked(*args):
        log("help_clicked%s opening '%s'", args, link)
        start_thread(open_link, "open-link", True)
    icon = get_icon_pixbuf(icon_name)
    btn = imagebutton("" if icon else label, icon, label, help_clicked, 12, False)
    return btn

def attach_label(table, label, tooltip_text=None, link=None):
    lbl = Gtk.Label(label)
    if tooltip_text:
        lbl.set_tooltip_text(tooltip_text)
    hbox = Gtk.HBox(False, 0)
    hbox.pack_start(xal(lbl), True, True)
    if link:
        help_btn = link_btn(link, "About %s" % label)
        hbox.pack_start(help_btn, False)
    table.attach(hbox)


class StartSession(Gtk.Window):

    def __init__(self, options):
        self.set_options(options)
        self.exit_code = None
        self.options_window = None
        self.default_config = get_defaults()
        #log("default_config=%s", self.default_config)
        #log("options=%s (%s)", options, type(options))
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

        self.display_box = Gtk.HBox(True, 20)
        options_box.pack_start(self.display_box, False, True, 20)
        self.display_label = l("Display:")
        self.display_entry = sf(Gtk.Entry())
        self.display_entry.connect('changed', self.display_changed)
        self.display_entry.set_width_chars(10)
        self.display_entry.set_placeholder_text("optional")
        self.display_entry.set_max_length(10)
        self.display_entry.set_tooltip_text("To use a specific X11 display number")
        self.display_combo = sf(Gtk.ComboBoxText())
        self.display_box.pack_start(self.display_label, True)
        self.display_box.pack_start(self.display_entry, True, False)
        self.display_box.pack_start(self.display_combo, True, False)

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
        # session options:
        hbox = Gtk.HBox(False, 12)
        hbox.pack_start(l("Options:"), True, False)
        for label_text, icon_name, tooltip_text, cb in (
            ("Features",    "features.png", "Session features", self.configure_features),
            ("Network",     "connect.png",  "Network options", self.configure_network),
            ("Display",     "display.png",  "Display settings", self.configure_display),
            ("Encodings",   "encoding.png", "Picture compression", self.configure_encoding),
            ("Keyboard",    "keyboard.png", "Keyboard layout and options", self.configure_keyboard),
            ("Audio",       "speaker.png",  "Audio forwarding options", self.configure_audio),
            ("Webcam",      "webcam.png",   "Webcam forwarding options", self.configure_webcam),
            ("Printing",    "printer.png",  "Printer forwarding options", self.configure_printing),
            ):
            icon = get_icon_pixbuf(icon_name)
            ib = imagebutton("", icon=icon, tooltip=label_text or tooltip_text,
                                  clicked_callback=cb, icon_size=32,
                                  label_font=Pango.FontDescription("sans 14"))
            hbox.pack_start(ib, True, False)
        options_box.pack_start(hbox, True, False)

        # Action buttons:
        hbox = Gtk.HBox(False, 20)
        vbox.pack_start(hbox, False, True, 20)
        def btn(label, tooltip, callback, default=False):
            ib = imagebutton(label, tooltip=tooltip, clicked_callback=callback, icon_size=32,
                            default=default, label_font=Pango.FontDescription("sans 16"))
            hbox.pack_start(ib)
            return ib
        self.cancel_btn = btn("Cancel", "",
                              self.quit)
        self.run_btn = btn("Start", "Start the xpra session",
                           self.run_command)
        self.runattach_btn = btn("Start & Attach", "Start the xpra session and attach to it",
                                 self.runattach_command, True)
        self.runattach_btn.set_sensitive(False)

        vbox.show_all()
        self.display_combo.hide()
        self.add(vbox)
        #load encodings in the background:
        self.load_codecs_thread = start_thread(self.load_codecs, "load-codecs", daemon=True)
        #poll the list of X11 displays in the background:
        self.display_list = ()
        if not OSX:
            self.load_displays_thread = start_thread(self.load_displays, "load-displays", daemon=True)

    def load_codecs(self):
        log("load_codecs()")
        from xpra.codecs.video_helper import getVideoHelper, NO_GFX_CSC_OPTIONS  #pylint: disable=import-outside-toplevel
        vh = getVideoHelper()
        vh.set_modules(video_decoders=self.session_options.video_decoders,
                       csc_modules=self.session_options.csc_modules or NO_GFX_CSC_OPTIONS)
        vh.init()
        from xpra.codecs.loader import load_codecs  #pylint: disable=import-outside-toplevel
        load_codecs()
        log("load_codecs() done")


    def no_display_combo(self):
        self.display_entry.show()
        self.display_combo.hide()

    def load_displays(self):
        log("load_displays()")
        while self.exit_code is None:
            time.sleep(1)
            if not self.shadow_btn.get_active() or not self.localhost_btn.get_active():
                GLib.idle_add(self.no_display_combo)
                continue
            try:
                from subprocess import Popen, PIPE
                cmd = get_xpra_command() + ["displays"]
                proc = Popen(cmd, stdout=PIPE, stderr=PIPE)
                out = proc.communicate(None, 5)[0]
            except Exception:
                log("failed to query the list of displays", exc_info=True)
            else:
                new_display_list = []
                if out:
                    for line in out.decode().splitlines():
                        if line.lower().startswith("#") or line.lower().startswith("found"):
                            continue
                        new_display_list.append(line.lstrip(" ").split(" ")[0])
                def populate_display_combo():
                    changed = self.display_list!=new_display_list
                    self.display_list = new_display_list
                    if not new_display_list:
                        self.no_display_combo()
                        return
                    self.display_entry.hide()
                    self.display_combo.show()
                    if not changed:
                        return
                    current = self.display_combo.get_active_text()
                    model = self.display_combo.get_model()
                    if model:
                        model.clear()
                    selected = 0
                    for i, display in enumerate(new_display_list):
                        self.display_combo.append_text(display)
                        if display==current:
                            selected = i
                    self.display_combo.set_active(selected)
                GLib.idle_add(populate_display_combo)

    def set_options(self, options):
        #cook some attributes,
        #so they won't trigger "changes" messages later
        #- we don't show "auto" as an option, convert to either true or false:
        options.splash = (str(options.splash) or "").lower() not in FALSE_OPTIONS
        options.xsettings = (str(options.xsettings) or "").lower() not in FALSE_OPTIONS
        self.session_options = options


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

    def run_dialog(self, WClass):
        log("run_dialog(%s) session_options=%s", WClass, repr_ellipsized(self.session_options))
        WClass(self.session_options, self.get_run_mode(), self).show()

    def configure_features(self, *_args):
        self.run_dialog(FeaturesWindow)
    def configure_network(self, *_args):
        self.run_dialog(NetworkWindow)
    def configure_display(self, *_args):
        self.run_dialog(DisplayWindow)
    def configure_encoding(self, *_args):
        if self.load_codecs_thread.is_alive():
            log("waiting for loader thread to complete")
            self.load_codecs_thread.join()
        self.run_dialog(EncodingWindow)
    def configure_keyboard(self, *_args):
        self.run_dialog(KeyboardWindow)
    def configure_audio(self, *_args):
        self.run_dialog(AudioWindow)
    def configure_webcam(self, *_args):
        self.run_dialog(WebcamWindow)
    def configure_printing(self, *_args):
        self.run_dialog(PrintingWindow)


    def populate_menus(self):
        localhost = self.localhost_btn.get_active()
        if (OSX or WIN32) and localhost:
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
            self.display_combo.hide()
            self.display_entry.show()
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
        if not (self.shadow_btn.get_active() and self.localhost_btn.get_active()):
            self.no_display_combo()

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
        if not (self.shadow_btn.get_active() and self.localhost_btn.get_active()):
            self.no_display_combo()


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
        log("do_run(%s) cmd=%s", attach, cmd)
        proc = exec_command(cmd)
        if proc:
            start_thread(self.wait_for_subprocess, "wait-%i" % proc.pid, daemon=True, args=(proc,))

    def wait_for_subprocess(self, proc):
        proc.wait()
        log("return code: %s", proc.returncode)
        GLib.idle_add(self.show)

    def get_run_mode(self):
        shadow = self.shadow_btn.get_active()
        seamless = self.seamless_btn.get_active()
        if seamless:
            return "start"
        if shadow:
            return "shadow"
        return "start-desktop"

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
        cmd = get_xpra_command() + [self.get_run_mode()]
        ewc = self.exit_with_client_cb.get_active()
        cmd.append("--exit-with-client=%s" % ewc)
        shadow = self.shadow_btn.get_active()
        if not shadow:
            ewc = self.exit_with_children_cb.get_active()
            cmd.append("--exit-with-children=%s" % ewc)
            if ewc:
                cmd.append("--start-child=%s" % command)
            else:
                cmd.append("--start=%s" % command)
        cmd.append("--attach=%s" % attach)
        #process session_config if we have one:
        for k in (
            "splash", "border", "headerbar", "notifications", "system-tray", "cursors", "bell", "modal-windows",
            "pixel-depth", "mousewheel",
            ):
            fn = k.replace("-", "_")
            if not hasattr(self.session_options, fn):
                continue
            value = getattr(self.session_options, fn)
            default_value = self.default_config.get(k)
            ot = OPTION_TYPES.get(k)
            if ot is bool:
                value = parse_bool(k, value)
            if value!=default_value:
                log.info("%s=%s (%s) - not %s (%s)", k, value, type(value), default_value, type(default_value))
                cmd.append("--%s=%s" % (k, value))
        localhost = self.localhost_btn.get_active()
        if self.display_entry.is_visible():
            display = self.display_entry.get_text().lstrip(":")
        else:
            display = self.display_combo.get_active_text()
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


class SessionOptions(Gtk.Window):
    def __init__(self, title, icon_name, options, run_mode, parent):
        Gtk.Window.__init__(self)
        self.options = options
        self.run_mode = run_mode
        self.set_title(title)
        self.set_border_width(20)
        self.set_resizable(True)
        self.set_decorated(True)
        self.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.set_transient_for(parent)
        self.set_modal(True)
        add_close_accel(self, self.close)
        self.connect("delete_event", self.close)
        icon = get_icon_pixbuf(icon_name)
        if icon:
            self.set_icon(icon)

        self.vbox = Gtk.VBox(False, 0)
        self.vbox.show()
        self.add(self.vbox)
        self.widgets = []
        self.populate_form()
        self.show()

    def populate_form(self):
        raise NotImplementedError()

    def close(self, *_args):  #pylint: disable=arguments-differ
        self.set_value_from_widgets()
        self.destroy()

    def sep(self, tb):
        tb.inc()
        hsep = Gtk.HSeparator()
        hsep.set_size_request(-1, 2)
        al = Gtk.Alignment(xalign=0.5, yalign=0.5, xscale=1, yscale=0)
        al.set_size_request(-1, 10)
        al.add(hsep)
        tb.attach(al, 0, 2)
        tb.inc()

    def bool_cb(self, table, label, option_name, tooltip_text=None, link=None):
        attach_label(table, label, tooltip_text, link)
        fn = option_name.replace("-", "_")
        value = getattr(self.options, fn)
        cb = Gtk.Switch()
        active = str(value).lower() not in FALSE_OPTIONS
        cb.set_active(active)
        al = xal(cb, xalign=0)
        table.attach(al, 1)
        setattr(self, "%s_widget" % fn, cb)
        setattr(self, "%s_widget_type" % fn, "bool")
        setattr(self, "%s_values" % fn, [value if not active else False, value if active else True])
        self.widgets.append(option_name)
        table.inc()
        return cb

    def radio_cb_auto(self, table, label, option_name, tooltip_text=None, link=None):
        return self.radio_cb(table, label, option_name, tooltip_text, link, {
            "yes"   : TRUE_OPTIONS,
            "no"    : FALSE_OPTIONS,
            "auto"  : ("auto", "", None),
            })

    def radio_cb(self, table, label, option_name, tooltip_text=None, link=None, options=None):
        attach_label(table, label, tooltip_text, link)
        fn = option_name.replace("-", "_")
        widget_base_name = "%s_widget" % fn
        setattr(self, "%s_widget_type" % fn, "radio")
        self.widgets.append(option_name)
        value = getattr(self.options, fn)
        #log.warn("%s=%s", fn, value)
        hbox = Gtk.HBox(True, 10)
        i = 0
        sibling = None
        btns = []
        saved_options = {}
        for label, match in options.items():
            btn = Gtk.RadioButton.new_with_label_from_widget(sibling, label)
            hbox.add(btn)
            setattr(self, "%s_%s" % (widget_base_name, label), btn)
            saved_match = match
            matched = value in match or str(value).lower() in match
            btn.set_active(matched)
            if matched:
                #ensure we save the current value first,
                #so that's what we will set as value when retrieving the form values:
                saved_match = [value]+list(match)
            if i==0:
                sibling = btn
            i += 1
            saved_options[label] = saved_match
            btns.append(btn)
        setattr(self, "%s_options" % fn, saved_options)
        table.attach(hbox, 1)
        table.inc()
        return btns

    def combo(self, table, label, option_name, options, link=None):
        attach_label(table, label, None, link)
        fn = option_name.replace("-", "_")
        value = getattr(self.options, fn)
        c = Gtk.ComboBoxText()
        index = None
        for i, (v, vlabel) in enumerate(options.items()):
            c.append_text(str(vlabel))
            if index is None or v==value:
                index = i
        if index is not None:
            c.set_active(index)
        al = Gtk.Alignment(xalign=0, yalign=0.5, xscale=0.0, yscale=1.0)
        al.add(c)
        table.attach(al, 1)
        setattr(self, "%s_widget" % fn, c)
        setattr(self, "%s_widget_type" % fn, "combo")
        setattr(self, "%s_options" % fn, options)
        self.widgets.append(option_name)
        table.inc()
        return c

    def scale(self, table, label, option_name, minv=0, maxv=100, marks=None):
        attach_label(table, label)
        fn = option_name.replace("-", "_")
        value = getattr(self.options, fn)
        #c = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, minv, maxv, 10)
        c = Gtk.Scale.new(Gtk.Orientation.HORIZONTAL)
        c.set_range(minv, maxv)
        c.set_draw_value(True)
        c.set_digits(0)
        c.set_hexpand(True)
        c.set_value(value or 0)
        c.set_valign(Gtk.Align.START)
        if marks:
            for v,label in marks.items():
                c.add_mark(v, Gtk.PositionType.BOTTOM, label)
        table.attach(c, 1)
        setattr(self, "%s_widget" % fn, c)
        setattr(self, "%s_widget_type" % fn, "scale")
        self.widgets.append(option_name)
        table.inc()
        return c

    def set_value_from_widgets(self):
        for option_name in self.widgets:
            self.set_value_from_widget(option_name)

    def set_value_from_widget(self, option_name):
        fn = option_name.replace("-", "_")
        widget_type = getattr(self, "%s_widget_type" % fn)
        if widget_type=="bool":
            values = self.valuesfromswitch(option_name)
        elif widget_type=="radio":
            values = self.valuesfromradio(option_name)
        elif widget_type=="combo":
            values = self.valuesfromcombo(option_name)
        elif widget_type=="scale":
            widget = getattr(self, "%s_widget" % fn)
            values = (int(widget.get_value()), )
        else:
            log.warn("unknown widget type '%s'", widget_type)
        if len(values)!=1 or values[0]!=UNSET:
            current_value = getattr(self.options, fn)
            for v in values:
                if current_value==v:
                    #unchanged
                    return
            #pick the first one:
            value = values[0]
            log.info("changed: %s=%r (%s) - was %r (%s)", fn, value, type(value), current_value, type(current_value))
            setattr(self.options, fn, value)

    def valuesfromswitch(self, option_name):
        fn = option_name.replace("-", "_")
        widget = getattr(self, "%s_widget" % fn)
        values = getattr(self, "%s_values" % fn)
        value = values[int(widget.get_active())]
        return (value, )

    def valuesfromradio(self, option_name):
        fn = option_name.replace("-", "_")
        options = getattr(self, "%s_options" % fn)
        widget_base_name = "%s_widget" % fn
        for label, match in options.items():
            btn = getattr(self, "%s_%s" % (widget_base_name, label))
            if btn.get_active():
                return match
        return (UNSET, )

    def valuesfromcombo(self, option_name):
        fn = option_name.replace("-", "_")
        widget = getattr(self, "%s_widget" % fn)
        options = getattr(self, "%s_options" % fn)
        value = widget.get_active_text()
        for k,v in options.items():
            if str(v)==value:
                return (k, )
        return (UNSET, )

    def table(self):
        tb = TableBuilder()
        table = tb.get_table()
        al = Gtk.Alignment(xalign=0.5, yalign=0.5, xscale=0.0, yscale=1.0)
        al.add(table)
        self.vbox.pack_start(al, expand=True, fill=True, padding=20)
        return tb


class FeaturesWindow(SessionOptions):
    def __init__(self, *args):
        super().__init__("Session Features", "features.png", *args)

    def populate_form(self):
        btn = link_btn("https://github.com/Xpra-org/xpra/blob/master/docs/Features/README.md",
                       label="Open Features Documentation", icon_name=None)
        self.vbox.pack_start(btn, expand=True, fill=False, padding=20)

        tb = self.table()
        self.bool_cb(tb, "Splash Screen", "splash", "Show a splash screen during startup")
        self.bool_cb(tb, "Read only", "readonly", "Mouse and keyboard events will be ignored")
        self.radio_cb(tb, "Border", "border", "Show a colored border around xpra windows to differentiate them", None, {
            "auto"  : ("auto,5:off", "auto"),
            "none"  : FALSE_OPTIONS,
            "blue"  : ("blue",),
            "red"   : ("red",),
            "green" : ("green", )
            })
        self.radio_cb(tb, "Header Bar", "headerbar", None, None, {
            "auto"  : ["auto"]+list(TRUE_OPTIONS),
            "no"    : FALSE_OPTIONS,
            "force" : ("force",),
            })
        self.sep(tb)
        #"https://github.com/Xpra-org/xpra/blob/master/docs/Features/Notifications.md")
        self.bool_cb(tb, "Xpra's System Tray", "tray")
        self.bool_cb(tb, "Forward System Trays", "system-tray")
        self.bool_cb(tb, "Notifications", "notifications")
        #"https://github.com/Xpra-org/xpra/blob/master/docs/Features/System-Tray.md")
        #self.bool_cb(tb, "Cursors", "cursors")
        #self.bool_cb(tb, "Bell", "bell")
        self.bool_cb(tb, "Modal Windows", "modal-windows")
        self.sep(tb)
        #"https://github.com/Xpra-org/xpra/blob/master/docs/Features/Image-Depth.md")
        self.combo(tb, "Mouse Wheel", "mousewheel", {
            "on" : "on",
            "no" : "disabled",
            "invert-x" : "invert X axis",
            "invert-y" : "invert Y axis",
            "invert-z" : "invert Z axis",
            "invert-all" : "invert all axes",
            })
        self.combo(tb, "Clipboard", "clipboard-direction", {
            "both"      : "enabled",
            "to-server" : "to server only",
            "to-client" : "to client only",
            "disabled"  : "disabled",
            })
        if POSIX and not OSX and not is_Wayland():
            self.bool_cb(tb, "XSettings", "xsettings")
        self.vbox.show_all()


class NetworkWindow(SessionOptions):
    def __init__(self, *args):
        super().__init__("Network Options", "connect.png", *args)

    def populate_form(self):
        btn = link_btn("https://github.com/Xpra-org/xpra/blob/master/docs/Network/README.md",
                       label="Open Network Documentation", icon_name=None)
        self.vbox.pack_start(btn, expand=True, fill=False, padding=20)

        tb = self.table()
        #"https://github.com/Xpra-org/xpra/blob/master/docs/Network/Multicast-DNS.md")
        self.radio_cb_auto(tb, "Session Sharing", "sharing")
        self.radio_cb_auto(tb, "Session Lock", "lock", "Prevent sessions from being taken over by new clients")
        self.sep(tb)
        self.bool_cb(tb, "Multicast DNS", "mdns", "Publish the session via mDNS")
        self.bool_cb(tb, "Bandwidth Detection", "bandwidth-detection", "Automatically detect runtime bandwidth limits")
        bwoptions = {
            "auto" : "Auto",
            }
        for bwlimit in BANDWIDTH_MENU_OPTIONS:
            if bwlimit<=0:
                s = "None"
            elif bwlimit>=10*1000*1000:
                s = "%iMbps" % (bwlimit//(1000*1000))
            else:
                s = "%sbps" % std_unit_dec(bwlimit)
            bwoptions[bwlimit] = s
        self.combo(tb, "Bandwidth Limit", "bandwidth-limit", bwoptions)
        #ssl options
        #ssh=paramiko | plink
        #exit-ssh
        #Remote Logging
        #open-files
        #open-url
        #file-size-limit
        self.vbox.show_all()


class DisplayWindow(SessionOptions):
    def __init__(self, *args):
        super().__init__("Display Settings", "display.png", *args)

    def populate_form(self):
        btn = link_btn("https://github.com/Xpra-org/xpra/blob/master/docs/Features/Display.md",
                       label="Open Display Documentation", icon_name=None)
        self.vbox.pack_start(btn, expand=True, fill=False, padding=20)

        tb = self.table()
        pixel_depths = {0   : "auto"}
        if self.run_mode=="shadow":
            pixel_depths[8] = 8
        for pd in (16, 24, 30, 32):
            pixel_depths[pd] = pd
        if self.run_mode=="start-desktop":
            size_options = {
                "yes"    : "auto",
                }
            for size in SCREEN_SIZES:
                try:
                    w, h = size.split("x")
                    size_options["%sx%s" % (w, h)] = "%s x %s" % (w, h)
                except (TypeError, ValueError, IndexError):
                     size_options[size] = size
            self.combo(tb, "Screen Size", "resize-display", size_options)
        self.combo(tb, "Pixel Depth", "pixel-depth", pixel_depths)
        self.combo(tb, "DPI", "dpi", {
            0       : "auto",
            72      : "72",
            96      : "96",
            144     : "144",
            192     : "192",
            })
        self.combo(tb, "Desktop Scaling", "desktop-scaling", {
            "on"    : "auto",
            "no"    : "disabled",
            "50%"   : "50%",
            "100%"  : "100%",
            "150%"  : "150%",
            "200%"  : "200%",
            })
        self.radio_cb(tb, "OpenGL Acceleration", "opengl", None, None, {
            "probe" : "probe",
            "auto"  : ["auto"]+list(TRUE_OPTIONS),
            "no"    : FALSE_OPTIONS,
            "force" : ("force",),
            })
        self.vbox.show_all()


class EncodingWindow(SessionOptions):
    def __init__(self, *args):
        super().__init__("Picture Encoding", "encoding.png", *args)

    def populate_form(self):
        btn = link_btn("https://github.com/Xpra-org/xpra/blob/master/docs/Usage/Encodings.md",
                       label="Open Encodings Documentation", icon_name=None)
        self.vbox.pack_start(btn, expand=True, fill=False, padding=20)

        tb = self.table()
        self.scale(tb, "Minimum Quality", "min-quality", marks={
            0   : "Very Low",
            30  : "Low",
            50  : "Medium",
            75  : "High",
            100 : "Lossless",
            })
        self.scale(tb, "Minimum Speed", "min-speed", marks={
            0   : "Low Bandwidth",
            100 : "Low Latency",
            })
        self.sep(tb)
        self.combo(tb, "Auto-refresh", "auto-refresh-delay", {
            0       : "disabled",
            0.1     : "fast",
            0.15    : "normal",
            0.5     : "slow",
            })
        from xpra.client.mixins.encodings import get_core_encodings
        encodings = ["auto", "rgb"] + get_core_encodings()
        encodings.remove("rgb24")
        encodings.remove("rgb32")
        if "grayscale" not in encodings:
            encodings.append("grayscale")
        from xpra.codecs.loader import get_encoding_name
        encoding_options = dict((encoding, get_encoding_name(encoding)) for encoding in encodings)
        #opts.encodings
        self.combo(tb, "Encoding", "encoding", encoding_options)
        #tb.attach(Gtk.Label("Colourspace Modules"), 0)
        #tb.inc()
        #tb.attach(Gtk.Label("Video Encoders"), 0)
        #tb.inc()
        #tb.attach(Gtk.Label("Video Decoders"), 0)
        self.vbox.show_all()


class KeyboardWindow(SessionOptions):
    def __init__(self, *args):
        super().__init__("Keyboard Options", "keyboard.png", *args)

    def populate_form(self):
        btn = link_btn("https://github.com/Xpra-org/xpra/blob/master/docs/Features/Keyboard.md",
                       label="Open Keyboard Documentation", icon_name=None)
        self.vbox.pack_start(btn, expand=True, fill=False, padding=20)

        tb = self.table()
        if POSIX and not OSX:
            try:
                from xpra.x11.gtk_x11.gdk_display_source import init_gdk_display_source
                init_gdk_display_source()
            except Exception:
                pass
        from xpra.platform.keyboard import Keyboard
        kbd = Keyboard()  #pylint: disable=not-callable
        layouts = {
            ""  : "auto",
            }
        layouts.update(kbd.get_all_x11_layouts())
        self.combo(tb, "Keyboard Layout", "keyboard-layout", layouts)
        self.bool_cb(tb, "State Synchronization", "keyboard-sync")
        self.bool_cb(tb, "Raw Mode", "keyboard-raw")
        self.combo(tb, "Input Method", "input-method", {
            "auto"  : "auto",
            "none"  : "default",
            "keep"  : "unchanged",
            "xim"   : "xim",
            "IBus"  : "IBus",
            "SCIM"  : "SCIM",
            "uim"   : "uim",
            })
        self.combo(tb, "Shortcut Modifiers", "shortcut-modifiers", {
            "auto"  : "auto",
            "shift + control"   : "Shift+Control",
            "control + alt"     : "Control+Alt",
            "shift + alt"       : "Shift+Alt",
            })
        self.vbox.show_all()


class AudioWindow(SessionOptions):
    def __init__(self, *args):
        super().__init__("Audio Options", "speaker.png", *args)

    def populate_form(self):
        btn = link_btn("https://github.com/Xpra-org/xpra/blob/master/docs/Features/Audio.md",
                       label="Open Audio Documentation", icon_name=None)
        self.vbox.pack_start(btn, expand=True, fill=False, padding=20)

        tb = self.table()
        self.radio_cb(tb, "Speaker", "speaker", None, None, {
            "on"        : TRUE_OPTIONS,
            "off"       : FALSE_OPTIONS,
            "disabled"  : ("disabled", ),
            })
        self.sep(tb)
        #tb.attach(Gtk.Label("Speaker Codec"))
        #self.speaker_codec_widget = Gtk.ComboBoxText()
        #for v in ("mp3", "wav"):
        #    self.speaker_codec_widget.append_text(v)
        #tb.attach(self.speaker_codec_widget, 1)
        #tb.inc()
        self.radio_cb(tb, "Microphone", "microphone", None, None, {
            "on"        : TRUE_OPTIONS,
            "off"       : FALSE_OPTIONS,
            "disabled"  : ("disabled", ),
            })
        self.sep(tb)
        #tb.attach(Gtk.Label("Microphone Codec"))
        #self.microphone_codec_widget = Gtk.ComboBoxText()
        #for v in ("mp3", "wav"):
        #    self.microphone_codec_widget.append_text(v)
        #tb.attach(self.microphone_codec_widget, 1)
        #tb.inc()
        self.bool_cb(tb, "AV Sync", "av-sync")
        self.vbox.show_all()


class WebcamWindow(SessionOptions):
    def __init__(self, *args):
        super().__init__("Webcam", "webcam.png", *args)

    def populate_form(self):
        btn = link_btn("https://github.com/Xpra-org/xpra/blob/master/docs/Features/Webcam.md",
                       label="Open Webcam Documentation", icon_name=None)
        self.vbox.pack_start(btn, expand=True, fill=False, padding=20)

        tb = self.table()
        cb = self.bool_cb(tb, "Webcam", "webcam")
        if OSX or WIN32:
            cb.set_sensitive(False)
            cb.set_active(False)
            tb.inc()
            tb.attach(Gtk.Label(""), 0, 2)
            tb.inc()
            tb.attach(Gtk.Label("Webcam forwarding is not supported on %s" % platform_name()), 0, 2)
        self.vbox.show_all()


class PrintingWindow(SessionOptions):
    def __init__(self, *args):
        super().__init__("Printer", "printer.png", *args)

    def populate_form(self):
        btn = link_btn("https://github.com/Xpra-org/xpra/blob/master/docs/Features/Printing.md",
                       label="Open Printing Documentation", icon_name=None)
        self.vbox.pack_start(btn, expand=True, fill=False, padding=20)

        tb = self.table()
        #self.bool_cb(tb, "Printing", "printing")
        self.radio_cb_auto(tb, "Printing", "printing")
        self.vbox.show_all()


def main(options=None): # pragma: no cover
    from xpra.platform import program_context
    from xpra.log import enable_color
    from xpra.platform.gui import init, ready
    with program_context("xpra-start-gui", "Xpra Start GUI"):
        enable_color()
        init()
        gui = StartSession(options)
        register_os_signals(gui.app_signal)
        ready()
        gui.session_toggled()
        if WIN32 or OSX:
            gui.remote_btn.set_active(True)
        gui.show()
        gui.present()
        Gtk.main()
        log("do_main() gui.exit_code=%s", gui.exit_code)
        return gui.exit_code


if __name__ == "__main__":  # pragma: no cover
    r = main()
    sys.exit(r)
