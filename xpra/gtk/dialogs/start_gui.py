# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import time
import shlex
import os.path
from collections import deque
from subprocess import Popen, PIPE
from urllib.parse import urlencode
from collections.abc import Callable

from xpra.util.glib import register_os_signals
from xpra.gtk.window import add_close_accel
from xpra.gtk.widget import imagebutton, label, setfont, switch
from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.gtk.dialogs.common_style import (
    add_style_class, style_actions, style_body, style_button, style_window,
)
from xpra.util.str_fn import repr_ellipsized
from xpra.util.i18n import _
from xpra.common import noop
from xpra.os_util import OSX, WIN32, gi_import
from xpra.util.system import platform_name, is_X11
from xpra.util.stats import std_unit_dec
from xpra.config.defaults import get_defaults
from xpra.config.types import OPTION_TYPES
from xpra.util.parsing import TRUE_OPTIONS, FALSE_OPTIONS, str_to_bool
from xpra.client.gtk3.menu_helper import BANDWIDTH_MENU_OPTIONS
from xpra.util.objects import AtomicInteger
from xpra.util.thread import check_main_thread, start_thread
from xpra.platform.paths import get_xpra_command
from xpra.log import Logger

log = Logger("client", "util")

GLib = gi_import("GLib")
Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")

SCREEN_SIZES = os.environ.get("XPRA_SCREEN_SIZES", "1024x768,1600x1200,1920x1080,2560x1600,3840x2160").split(",")

try:
    import xdg
except ImportError:
    xdg = None

REQUIRE_COMMAND = False

UNSET = object()


def exec_command(cmd, **kwargs):
    env = os.environ.copy()
    env["XPRA_WAIT_FOR_INPUT"] = "0"
    env["XPRA_NOTTY"] = "1"
    proc = Popen(cmd, env=env, **kwargs)
    log("exec_command(%s)=%s", cmd, proc)
    return proc


def xal(widget, xalign=1.0):
    al = Gtk.Alignment(xalign=xalign, yalign=0.5, xscale=0, yscale=0)
    al.add(widget)
    return al


def sf(w, font="sans 14"):
    setfont(w, font)
    return w


def l(text):  # noqa: E743
    widget = label(_(text))
    return sf(widget)


def link_btn(link: str, text="", icon_name="question.png"):
    def open_link() -> None:
        import webbrowser
        webbrowser.open(link)

    def help_clicked(*args) -> None:
        log("help_clicked%s opening '%s'", args, link)
        start_thread(open_link, "open-link", True)

    icon = get_icon_pixbuf(icon_name)
    btn = imagebutton("" if icon else _(text), icon, _(text), help_clicked, 12, False)
    add_style_class(btn, "flat")
    return btn


MODE_NESTED_SSH = "SSH -> SSH"
WSL_DEFAULT_DISTRIBUTION = "Default distribution"
# where the server in WSL starts looking for a free display, see `XPRA_FIRST_FREE_DISPLAY`:
WSL_FIRST_DISPLAY = 100
# how many lines of output we show when a WSL session fails to start:
WSL_ERROR_LINES = 20


def get_default_port(mode):
    return {
        "SSH": 22,
        MODE_NESTED_SSH: 22,
    }.get(mode, 14500)


class StartSession(Gtk.Window):

    def __init__(self, options):
        check_main_thread()
        self.set_options(options)
        self.exit_code = None
        self.options_window = None
        self.default_config = get_defaults()
        super().__init__()
        style_window(self, "start-session-dialog")
        self.set_title(_("Start Xpra Session"))
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_size_request(640, 300)
        if icon := get_icon_pixbuf("xpra.png"):
            self.set_icon(icon)
        self.connect("delete-event", self.quit)
        add_close_accel(self, self.quit)

        vbox = Gtk.VBox(homogeneous=False, spacing=0)
        vbox.set_spacing(10)
        style_body(vbox)

        # choose the session type:
        hbox = Gtk.HBox(homogeneous=True, spacing=40)
        add_style_class(hbox, "xpra-card")

        def rb(sibling=None, text="", cb: Callable = noop, tooltip_text="") -> Gtk.RadioButton:
            btn = Gtk.RadioButton.new_with_label_from_widget(sibling, _(text))
            if cb != noop:
                btn.connect("toggled", cb)
            if tooltip_text:
                btn.set_tooltip_text(_(tooltip_text))
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

        options_box = Gtk.VBox(homogeneous=False, spacing=10)
        add_style_class(options_box, "xpra-card")
        vbox.pack_start(options_box, True, False, 20)
        # select host:
        host_box = Gtk.HBox(homogeneous=True, spacing=20)
        options_box.pack_start(host_box, False)
        self.host_label = l("Host:")
        hbox = Gtk.HBox(homogeneous=True, spacing=0)
        host_box.pack_start(self.host_label, True)
        host_box.pack_start(hbox, True, True)
        self.localhost_btn = rb(None, "Local System", self.host_toggled)
        self.remote_btn = rb(self.localhost_btn, "Remote")
        self.remote_btn.set_tooltip_text(_("Start sessions on a remote system"))
        self.wsl_btn = None
        if WIN32:
            self.wsl_btn = rb(self.localhost_btn, "WSL", self.host_toggled,
                              "Start seamless sessions in a Windows Subsystem for Linux distribution")
        self.address_box = Gtk.HBox(homogeneous=False, spacing=0)
        options_box.pack_start(xal(self.address_box), True, True)
        self.mode_combo = sf(Gtk.ComboBoxText())
        self.address_box.pack_start(xal(self.mode_combo), False)
        for mode in ("SSH", MODE_NESTED_SSH, "TCP", "SSL", "WS", "WSS", "QUIC"):
            self.mode_combo.append_text(mode)
        self.mode_combo.set_active(0)
        self.mode_combo.connect("changed", self.mode_changed)
        self.username_entry = sf(Gtk.Entry())
        self.username_entry.set_width_chars(12)
        self.username_entry.set_placeholder_text(_("Username"))
        self.username_entry.set_max_length(255)
        self.address_box.pack_start(xal(self.username_entry), False)
        self.address_box.pack_start(l("@"), False)
        self.host_entry = sf(Gtk.Entry())
        self.host_entry.set_width_chars(24)
        self.host_entry.set_placeholder_text(_("Hostname or IP address"))
        self.host_entry.set_max_length(255)
        self.address_box.pack_start(xal(self.host_entry), False)
        self.address_box.pack_start(label(":"), False)
        self.port_entry = sf(Gtk.Entry())
        self.port_entry.set_text("22")
        self.port_entry.set_width_chars(5)
        self.port_entry.set_placeholder_text(_("Port"))
        self.port_entry.set_max_length(5)
        self.address_box.pack_start(xal(self.port_entry, 0), False)

        # WSL: the distribution and Linux user, `wsl.exe` takes care of the connection
        self.wsl_box = Gtk.HBox(homogeneous=False, spacing=10)
        options_box.pack_start(xal(self.wsl_box), True, True)
        self.wsl_box.pack_start(l("WSL distribution:"), False)
        self.wsl_distribution_combo = sf(Gtk.ComboBoxText())
        self.wsl_distribution_combo.append_text(_(WSL_DEFAULT_DISTRIBUTION))
        self.wsl_distribution_combo.set_active(0)
        self.wsl_box.pack_start(self.wsl_distribution_combo, False)
        self.wsl_user_entry = sf(Gtk.Entry())
        self.wsl_user_entry.set_width_chars(12)
        self.wsl_user_entry.set_placeholder_text(_("Linux user"))
        self.wsl_user_entry.set_tooltip_text(_("optional, WSL's default user for the distribution otherwise"))
        self.wsl_user_entry.set_max_length(255)
        self.wsl_box.pack_start(self.wsl_user_entry, False)
        self.wsl_distributions_loading = False

        # ssh -> ssh: the proxy host to connect through
        self.proxy_box = Gtk.VBox(homogeneous=False, spacing=10)
        options_box.pack_start(self.proxy_box, True, True)
        hbox = Gtk.HBox(homogeneous=False, spacing=0)
        self.proxy_box.pack_start(xal(hbox), True, True)
        hbox.pack_start(l("Proxy: "), False)
        self.proxy_username_entry = sf(Gtk.Entry())
        self.proxy_username_entry.set_width_chars(12)
        self.proxy_username_entry.set_placeholder_text(_("Username"))
        self.proxy_username_entry.set_max_length(255)
        hbox.pack_start(xal(self.proxy_username_entry), False)
        hbox.pack_start(l("@"), False)
        self.proxy_host_entry = sf(Gtk.Entry())
        self.proxy_host_entry.set_width_chars(24)
        self.proxy_host_entry.set_placeholder_text(_("Proxy hostname or IP address"))
        self.proxy_host_entry.set_max_length(255)
        hbox.pack_start(xal(self.proxy_host_entry), False)
        hbox.pack_start(label(":"), False)
        self.proxy_port_entry = sf(Gtk.Entry())
        self.proxy_port_entry.set_text("22")
        self.proxy_port_entry.set_width_chars(5)
        self.proxy_port_entry.set_placeholder_text(_("Port"))
        self.proxy_port_entry.set_max_length(5)
        hbox.pack_start(xal(self.proxy_port_entry, 0), False)
        hbox = Gtk.HBox(homogeneous=False, spacing=10)
        self.proxy_box.pack_start(xal(hbox), True, True)
        self.proxy_password_entry = sf(Gtk.Entry())
        self.proxy_password_entry.set_width_chars(16)
        self.proxy_password_entry.set_placeholder_text(_("Proxy password"))
        self.proxy_password_entry.set_tooltip_text(_("optional"))
        self.proxy_password_entry.set_max_length(255)
        self.proxy_password_entry.set_visibility(False)
        hbox.pack_start(self.proxy_password_entry, False)
        self.proxy_key_entry = sf(Gtk.Entry())
        self.proxy_key_entry.set_width_chars(24)
        self.proxy_key_entry.set_placeholder_text(_("Proxy private key path"))
        self.proxy_key_entry.set_tooltip_text(_("optional"))
        self.proxy_key_entry.set_max_length(4096)
        hbox.pack_start(self.proxy_key_entry, False)

        self.display_box = Gtk.HBox(homogeneous=True, spacing=20)
        options_box.pack_start(self.display_box, False, True, 20)
        self.display_label = l("Display:")
        self.display_entry = sf(Gtk.Entry())
        self.display_entry.connect('changed', self.display_changed)
        self.display_entry.set_width_chars(10)
        self.display_entry.set_placeholder_text(_("optional"))
        self.display_entry.set_max_length(10)
        self.display_entry.set_tooltip_text(_("To use a specific X11 display number"))
        self.display_combo = sf(Gtk.ComboBoxText())
        self.display_box.pack_start(self.display_label, True)
        self.display_box.pack_start(self.display_entry, True, False)
        self.display_box.pack_start(self.display_combo, True, False)

        # Label:
        self.entry_box = Gtk.HBox(homogeneous=True, spacing=20)
        options_box.pack_start(self.entry_box, False, True, 20)
        self.entry_label = l("Command:")
        self.entry = sf(Gtk.Entry())
        self.entry.set_max_length(255)
        self.entry.set_width_chars(32)
        self.entry.connect('changed', self.entry_changed)
        self.entry_box.pack_start(self.entry_label, True)
        self.entry_box.pack_start(self.entry, True, False)

        # or use menus if we have xdg data:
        self.category_box = Gtk.HBox(homogeneous=True, spacing=20)
        options_box.pack_start(self.category_box, False)
        self.category_label = l("Category:")
        self.category_combo = sf(Gtk.ComboBoxText())
        self.category_box.pack_start(self.category_label, True)
        self.category_box.pack_start(self.category_combo, True, True)
        self.category_combo.connect("changed", self.category_changed)
        self.categories = {}

        self.command_box = Gtk.HBox(homogeneous=True, spacing=20)
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
        hbox = Gtk.HBox(homogeneous=False, spacing=20)
        options_box.pack_start(hbox, False)
        self.exit_with_children_cb = sf(Gtk.CheckButton())
        self.exit_with_children_cb.set_label(_("exit with application"))
        hbox.add(xal(self.exit_with_children_cb, 0.5))
        self.exit_with_children_cb.set_active(True)
        self.exit_with_client_cb = sf(Gtk.CheckButton())
        self.exit_with_client_cb.set_label(_("exit with client"))
        hbox.add(xal(self.exit_with_client_cb, 0.5))
        self.exit_with_client_cb.set_active(False)
        # session options:
        hbox = Gtk.HBox(homogeneous=False, spacing=12)
        hbox.pack_start(l("Options:"), True, False)
        for text, icon_name, tooltip_text, cb in (
                ("Features", "features.png", "Session features", self.configure_features),
                ("Network", "connect.png", "Network options", self.configure_network),
                ("Display", "display.png", "Display settings", self.configure_display),
                ("Encodings", "encoding.png", "Picture compression", self.configure_encoding),
                ("Keyboard", "keyboard.png", "Keyboard layout and options", self.configure_keyboard),
                ("Audio", "speaker.png", "Audio forwarding options", self.configure_audio),
                ("Webcam", "webcam.png", "Webcam forwarding options", self.configure_webcam),
                ("Printing", "printer.png", "Printer forwarding options", self.configure_printing),
        ):
            icon = get_icon_pixbuf(icon_name)
            ib = imagebutton("", icon=icon, tooltip=_(text or tooltip_text),
                             clicked_callback=cb, icon_size=32,
                             label_font="")
            style_button(ib)
            hbox.pack_start(ib, True, False)
        options_box.pack_start(hbox, True, False)

        # Action buttons:
        hbox = Gtk.HBox(homogeneous=False, spacing=20)
        style_actions(hbox)
        vbox.pack_end(hbox, False, False, 0)

        def btn(text, tooltip, callback, default=False) -> Gtk.Button:
            ib = imagebutton(_(text), tooltip=_(tooltip), clicked_callback=callback, icon_size=32,
                             default=default)
            style_button(ib, primary=default)
            hbox.pack_start(ib)
            return ib

        self.cancel_btn = btn("Cancel", "", self.quit)
        self.run_btn = btn("Start", "Start the xpra session",
                           self.run_command)
        self.runattach_btn = btn("Start & Attach", "Start the xpra session and attach to it",
                                 self.runattach_command, True)
        self.runattach_btn.set_sensitive(False)

        vbox.show_all()
        self.display_combo.hide()
        self.proxy_box.hide()
        self.wsl_box.hide()
        self.add(vbox)
        # load encodings in the background:
        self.load_codecs_thread = start_thread(self.load_codecs, "load-codecs", daemon=True)
        # poll the list of X11 displays in the background:
        self.display_list = ()
        if not OSX:
            self.load_displays_thread = start_thread(self.load_displays, "load-displays", daemon=True)

    def load_codecs(self) -> None:
        log("load_codecs()")
        from xpra.codecs.video import getVideoHelper  # pylint: disable=import-outside-toplevel
        vh = getVideoHelper()
        vh.set_modules(video_decoders=self.session_options.video_decoders,
                       csc_modules=self.session_options.csc_modules)
        vh.init()
        from xpra.codecs.loader import load_codecs, show_codecs  # pylint: disable=import-outside-toplevel
        load_codecs()
        show_codecs()
        log("load_codecs() done")

    def no_display_combo(self) -> None:
        self.display_entry.show()
        self.display_combo.hide()

    def load_displays(self) -> None:
        log("load_displays()")
        while self.exit_code is None:
            time.sleep(1)
            if not self.shadow_btn.get_active() or not self.localhost_btn.get_active():
                GLib.idle_add(self.no_display_combo)
                continue
            try:
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
                            # empty or header line
                            continue
                        if line.lower().find("mode=") >= 0:
                            # this is an xpra display, don't shadow it
                            continue
                        new_display_list.append(line.lstrip(" ").split(" ")[0])
                GLib.idle_add(self.populate_display_combo, new_display_list)

    def populate_display_combo(self, new_display_list) -> None:
        changed = self.display_list != new_display_list
        self.display_list = new_display_list
        if not new_display_list:
            self.no_display_combo()
            return
        self.display_entry.hide()
        self.display_combo.show()
        if not changed:
            return
        current = self.display_combo.get_active_text()
        if model := self.display_combo.get_model():
            model.clear()
        selected = 0
        for i, display in enumerate(new_display_list):
            self.display_combo.append_text(display)
            if display == current:
                selected = i
        self.display_combo.set_active(selected)

    def set_options(self, options):
        # cook some attributes,
        # so they won't trigger "changes" messages later
        # - we don't show "auto" as an option, convert to either true or false:
        options.splash = (str(options.splash) or "").lower() not in FALSE_OPTIONS
        options.xsettings = (str(options.xsettings) or "").lower() not in FALSE_OPTIONS
        self.session_options = options

    def app_signal(self, signum) -> None:
        if self.exit_code is None:
            self.exit_code = 128 + signum
        log("app_signal(%s) exit_code=%i", signum, self.exit_code)
        self.quit()

    def quit(self, *args) -> None:
        log("quit%s", args)
        if self.exit_code is None:
            self.exit_code = 0
        self.do_quit()

    def do_quit(self) -> None:
        log("do_quit()")
        Gtk.main_quit()

    def run_dialog(self, WClass: Callable):
        log("run_dialog(%s) session_options=%s", WClass, repr_ellipsized(self.session_options))
        WClass(self.session_options, self.get_run_mode(), self).show()

    def configure_features(self, *_args) -> None:
        self.run_dialog(FeaturesWindow)

    def configure_network(self, *_args) -> None:
        self.run_dialog(NetworkWindow)

    def configure_display(self, *_args) -> None:
        self.run_dialog(DisplayWindow)

    def configure_encoding(self, *_args) -> None:
        if self.load_codecs_thread.is_alive():
            log("waiting for loader thread to complete")
            self.load_codecs_thread.join()
        self.run_dialog(EncodingWindow)

    def configure_keyboard(self, *_args) -> None:
        self.run_dialog(KeyboardWindow)

    def configure_audio(self, *_args) -> None:
        self.run_dialog(AudioWindow)

    def configure_webcam(self, *_args) -> None:
        self.run_dialog(WebcamWindow)

    def configure_printing(self, *_args) -> None:
        self.run_dialog(PrintingWindow)

    def populate_menus(self) -> None:
        localhost = self.localhost_btn.get_active()
        if (OSX or WIN32) and localhost:
            self.display_box.hide()
        else:
            self.display_box.show()
        shadow_mode = self.shadow_btn.get_active()
        seamless = self.seamless_btn.get_active()
        if self.remote_btn.get_active():
            self.address_box.show_all()
        else:
            self.address_box.hide()
        if self.is_wsl():
            self.wsl_box.show_all()
        else:
            self.wsl_box.hide()
        self.show_proxy_box()
        if shadow_mode:
            # only option we show is the optional display input
            self.entry_box.hide()
            self.category_box.hide()
            self.command_box.hide()
            self.exit_with_children_cb.hide()
        else:
            self.display_combo.hide()
            self.display_entry.show()
            self.exit_with_children_cb.show()
            if xdg and localhost:
                # we have the xdg menus and the server is local, so we can use them:
                self.entry_box.hide()
                self.command_label.set_text(_("Command:") if seamless else _("Desktop Environment:"))
                self.command_box.show_all()
                if seamless:
                    self.category_box.show()
                    self.populate_category()
                else:
                    self.category_box.hide()
                    self.populate_command()
                self.exit_with_children_cb.set_sensitive(True)
            else:
                # remote server (or missing xdg data)
                self.command_box.hide()
                self.category_box.hide()
                self.entry_label.set_text(_("Command:") if seamless else _("Desktop Environment:"))
                self.entry_box.show_all()
                has_entry = bool(self.entry.get_text())
                self.exit_with_children_cb.set_active(has_entry)
                self.exit_with_children_cb.set_sensitive(has_entry)

    def populate_category(self) -> None:
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
        if model := self.category_combo.get_model():
            model.clear()
        for name in sorted(self.categories.keys()):
            self.category_combo.append_text(name)
        if self.categories:
            self.category_combo.set_active(0)

    def category_changed(self, *args) -> None:
        category = self.category_combo.get_active_text()
        log("category_changed(%s) category=%s", args, category)
        self.commands = {}
        self.desktop_entry = None
        if category:
            from xdg.Menu import Menu, MenuEntry
            # find the matching submenu:
            submenu = self.categories[category]
            assert isinstance(submenu, Menu)
            for entry in submenu.getEntries():
                # can we have more than 2 levels of submenus?
                if isinstance(entry, MenuEntry):
                    name = entry.DesktopEntry.getName()
                    self.commands[name] = entry.DesktopEntry
        self.command_combo.get_model().clear()
        for name in sorted(self.commands.keys()):
            self.command_combo.append_text(name)
        if self.commands:
            self.command_combo.set_active(0)
        self.command_box.show()

    def populate_command(self) -> None:
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

    def command_changed(self, *args) -> None:
        if self.shadow_btn.get_active():
            return
        name = self.command_combo.get_active_text()
        log("command_changed(%s) command=%s", args, name)
        if name:
            if self.seamless_btn.get_active():
                self.desktop_entry = self.commands[name]
            else:
                self.desktop_entry = self.xsessions[name]
            log("command_changed(%s) desktop_entry=%s", args, self.desktop_entry)
        else:
            self.desktop_entry = None
        self.run_btn.set_sensitive(not REQUIRE_COMMAND or bool(name))
        self.runattach_btn.set_sensitive(not REQUIRE_COMMAND or bool(name))

    def entry_changed(self, *args) -> None:
        if self.shadow_btn.get_active():
            return
        text = self.entry.get_text()
        log("entry_changed(%s) entry=%s", args, text)
        localhost = self.localhost_btn.get_active()
        self.exit_with_children_cb.set_sensitive(bool(text) or (xdg and localhost))
        self.run_btn.set_sensitive(not REQUIRE_COMMAND or bool(text))
        self.runattach_btn.set_sensitive(not REQUIRE_COMMAND or bool(text))

    def mode_changed(self, *args) -> None:
        log("mode_changed(%s)", args)
        mode = self.mode_combo.get_active_text()
        self.port_entry.set_text(str(get_default_port(mode)))
        self.show_proxy_box()
        if not (self.shadow_btn.get_active() and self.localhost_btn.get_active()):
            self.no_display_combo()

    def show_proxy_box(self) -> None:
        nested = self.remote_btn.get_active() and self.mode_combo.get_active_text() == MODE_NESTED_SSH
        if nested:
            self.proxy_box.show_all()
        else:
            self.proxy_box.hide()

    def session_toggled(self, *args) -> None:
        localhost = self.localhost_btn.get_active()
        log("session_toggled(%s) localhost=%s", args, localhost)
        shadow = self.shadow_btn.get_active()
        local_shadow_only = WIN32 or OSX
        if shadow:
            self.exit_with_client_cb.set_active(True)
        elif local_shadow_only and localhost:
            # can only do shadow on localhost, so switch to remote:
            self.remote_btn.set_active(True)
        can_use_localhost = shadow or not local_shadow_only
        self.localhost_btn.set_sensitive(can_use_localhost)
        self.localhost_btn.set_tooltip_text(_("Start sessions on the local system") if can_use_localhost else
                                            _("Cannot start local desktop or seamless sessions on %s") % platform_name())
        self.display_changed()
        self.populate_menus()
        self.entry_changed()

    def display_changed(self, *args) -> None:
        display = self.display_entry.get_text().lstrip(":")
        localhost = self.localhost_btn.get_active()
        shadow = self.shadow_btn.get_active()
        log("display_changed(%s) display=%s, localhost=%s, shadow=%s", args, display, localhost, shadow)
        ra_label = _("Start the xpra session and attach to it")
        self.runattach_btn.set_sensitive(True)
        if shadow and localhost:
            if WIN32 or OSX or (not display or os.environ.get("DISPLAY", "").lstrip(":") == display):
                ra_label = _("Cannot attach this desktop session to itself")
                self.runattach_btn.set_sensitive(False)
        self.runattach_btn.set_tooltip_text(ra_label)

    def is_wsl(self) -> bool:
        return bool(self.wsl_btn and self.wsl_btn.get_active())

    def update_wsl_session_types(self) -> None:
        # only seamless sessions are supported with WSL for now:
        wsl = self.is_wsl()
        for btn in (self.desktop_btn, self.shadow_btn):
            btn.set_sensitive(not wsl)
        if not wsl:
            self.display_entry.set_placeholder_text(_("optional"))
            self.display_entry.set_tooltip_text(_("To use a specific X11 display number"))
            return
        if not self.seamless_btn.get_active():
            self.seamless_btn.set_active(True)
        # the session should survive the client disconnecting:
        self.exit_with_client_cb.set_active(False)
        # an empty display lets the server choose a free one:
        self.display_entry.set_placeholder_text(_("automatic"))
        self.display_entry.set_tooltip_text(_("To use a specific X11 display number,\n"
                                              "leave empty to use the first free one from %s") % WSL_FIRST_DISPLAY)
        if not self.wsl_distributions_loading:
            self.wsl_distributions_loading = True
            start_thread(self.load_wsl_distributions, "wsl-list-distributions", daemon=True)

    def load_wsl_distributions(self) -> None:
        # this can take a while if WSL has to start, so it runs in its own thread
        from xpra.net.wsl import list_distributions
        try:
            distributions = list_distributions()
        except Exception as e:
            log("list_distributions()", exc_info=True)
            GLib.idle_add(self.show_error, _("Cannot list the WSL distributions"), str(e))
            distributions = []
        GLib.idle_add(self.populate_wsl_distributions, distributions)

    def populate_wsl_distributions(self, distributions: list[str]) -> None:
        self.wsl_distributions_loading = False
        current = self.wsl_distribution_combo.get_active_text()
        if model := self.wsl_distribution_combo.get_model():
            model.clear()
        self.wsl_distribution_combo.append_text(_(WSL_DEFAULT_DISTRIBUTION))
        selected = 0
        for i, distribution in enumerate(distributions):
            self.wsl_distribution_combo.append_text(distribution)
            if distribution == current:
                selected = i + 1
        self.wsl_distribution_combo.set_active(selected)

    def get_wsl_distribution(self) -> str:
        if self.wsl_distribution_combo.get_active() <= 0:
            return ""
        return self.wsl_distribution_combo.get_active_text() or ""

    def show_error(self, title: str, text: str) -> None:
        dialog = Gtk.MessageDialog(transient_for=self, flags=0, message_type=Gtk.MessageType.ERROR,
                                   buttons=Gtk.ButtonsType.CLOSE, text=title)
        dialog.format_secondary_text(text)
        dialog.connect("response", lambda *_args: dialog.destroy())
        dialog.show_all()

    def host_toggled(self, *args) -> None:
        log("host_toggled(%s)", args)
        self.update_wsl_session_types()
        self.display_changed()
        self.populate_menus()
        self.entry_changed()
        if not (self.shadow_btn.get_active() and self.localhost_btn.get_active()):
            self.no_display_combo()

    def hide_window(self, *args) -> bool:
        log("hide_window%s", args)
        self.hide()
        return True

    def run_command(self, *_args) -> None:
        self.do_run()

    def runattach_command(self, *_args) -> None:
        self.do_run(True)

    def do_run(self, attach=False) -> None:
        cmd = self.get_run_command(attach)
        # only hide after reading the form:
        self.hide()
        log("do_run(%s) cmd=%s", attach, cmd)
        if self.is_wsl():
            distribution = self.get_wsl_distribution()
            username = self.wsl_user_entry.get_text()
            start_thread(self.run_wsl, "run-wsl", daemon=True, args=(cmd, distribution, username))
            return
        if proc := exec_command(cmd):
            start_thread(self.wait_for_subprocess, "wait-%i" % proc.pid, daemon=True, args=(proc,))

    @staticmethod
    def get_wsl_executable(cmd: list[str]) -> str:
        # ie: ["xpra", "seamless", "--start=xterm -fa Mono", ...] -> "xterm"
        for arg in cmd:
            for option in ("--start=", "--start-child="):
                if arg.startswith(option):
                    try:
                        return shlex.split(arg[len(option):])[0]
                    except (ValueError, IndexError):
                        return ""
        return ""

    def run_wsl(self, cmd: list[str], distribution: str, username: str) -> None:
        # check that xpra can be found before trying to start a session with it,
        # so we can show installation instructions instead of an obscure error:
        from xpra.net.wsl import check_xpra, check_command
        message = check_xpra(distribution, username)
        if not message and (command := self.get_wsl_executable(cmd)):
            # the server would start without the application, and we would never know:
            message = check_command(command, distribution, username)
        if message:
            GLib.idle_add(self.show_error, _("Cannot start the WSL session"), message)
            GLib.idle_add(self.show)
            return
        proc = exec_command(cmd, stdout=PIPE, stderr=PIPE)
        # keep the last lines of output, so we can show why the session failed to start:
        output: deque[str] = deque(maxlen=WSL_ERROR_LINES)

        def drain(pipe) -> None:
            for line in iter(pipe.readline, b""):
                if s := line.decode("utf8", errors="replace").rstrip():
                    log("wsl session: %s", s)
                    output.append(s)

        drain_threads = [start_thread(drain, "drain-output", daemon=True, args=(pipe,))
                         for pipe in (proc.stdout, proc.stderr)]
        proc.wait()
        for thread in drain_threads:
            thread.join(1)
        log("return code: %s", proc.returncode)
        if proc.returncode not in (0, None):
            from xpra.exit_codes import exit_str
            details = "\n".join([exit_str(proc.returncode)] + list(output))
            GLib.idle_add(self.show_error, _("The WSL session failed"), details)
        GLib.idle_add(self.show)

    def wait_for_subprocess(self, proc: Popen) -> None:
        proc.wait()
        log("return code: %s", proc.returncode)
        GLib.idle_add(self.show)

    def get_run_mode(self) -> str:
        shadow = self.shadow_btn.get_active()
        if self.seamless_btn.get_active():
            return "seamless"
        if shadow:
            return "shadow"
        return "desktop"

    def get_run_command(self, attach=False) -> list[str]:
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
        # process session_config if we have one:
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
                value = str_to_bool(value)
            if value != default_value:
                log.info("%s=%s (%s) - not %s (%s)", k, value, type(value), default_value, type(default_value))
                cmd.append(f"--{k}={value}")
        localhost = self.localhost_btn.get_active()
        if self.display_entry.is_visible():
            display = self.display_entry.get_text().lstrip(":")
        else:
            display = self.display_combo.get_active_text()
        if localhost:
            uri = ":" + display if display else ""
        elif self.is_wsl():
            from xpra.net.wsl import wsl_target_string
            uri = wsl_target_string(self.get_wsl_distribution(), self.wsl_user_entry.get_text(), display)
        else:
            mode = self.mode_combo.get_active_text()
            scheme = "ssh" if mode == MODE_NESTED_SSH else mode.lower()
            uri = f"{scheme}://"
            if username := self.username_entry.get_text():
                uri += f"{username}@"
            if host := self.host_entry.get_text():
                uri += host
            try:
                port = int(self.port_entry.get_text())
            except ValueError:
                port = 0
            if port and port != get_default_port(mode):
                uri += f":{port}"
            uri += "/"
            if display:
                uri += display
            if mode == MODE_NESTED_SSH:
                uri += self.get_proxy_query()
        if uri:
            cmd.append(uri)
        return cmd

    def get_proxy_query(self) -> str:
        proxy = {}
        if host := self.proxy_host_entry.get_text():
            proxy["proxy_host"] = host
        try:
            port = int(self.proxy_port_entry.get_text())
        except ValueError:
            port = 0
        if port and port != 22:
            proxy["proxy_port"] = port
        for k, entry in {
            "proxy_username": self.proxy_username_entry,
            "proxy_password": self.proxy_password_entry,
            "proxy_key": self.proxy_key_entry,
        }.items():
            if value := entry.get_text():
                proxy[k] = value
        return "?" + urlencode(proxy) if proxy else ""


class SessionOptions(Gtk.Window):
    def __init__(self, title, icon_name, options, run_mode, parent):
        check_main_thread()
        super().__init__()
        style_window(self, "session-options-dialog")
        self.options = options
        self.run_mode = run_mode
        self.set_title(_(title))
        self.set_resizable(True)
        self.set_decorated(True)
        self.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.set_transient_for(parent)
        self.set_modal(True)
        add_close_accel(self, self.close)
        self.connect("delete_event", self.close)
        if icon := get_icon_pixbuf(icon_name):
            self.set_icon(icon)

        self.vbox = Gtk.VBox(homogeneous=False, spacing=0)
        style_body(self.vbox)
        self.vbox.show()
        self.add(self.vbox)
        self.add_grid()
        self.row = AtomicInteger()
        self.widgets = []
        self.populate_form()
        self.show()

    def add_grid(self) -> None:
        self.grid = Gtk.Grid()
        self.grid.set_column_spacing(12)
        self.grid.set_row_spacing(4)
        add_style_class(self.grid, "xpra-card", "xpra-table")
        self.grid.show()
        al = Gtk.Alignment(xalign=0.5, yalign=0.5, xscale=0.0, yscale=1.0)
        al.add(self.grid)
        al.show()
        self.vbox.pack_start(al, expand=True, fill=True, padding=20)

    def populate_form(self) -> None:
        raise NotImplementedError()

    def close(self, *_args) -> None:  # pylint: disable=arguments-differ
        self.set_value_from_widgets()
        super().close()

    def sep(self) -> None:
        hsep = Gtk.HSeparator()
        hsep.set_size_request(-1, 2)
        hsep.set_margin_top(5)
        hsep.set_margin_bottom(5)
        al = Gtk.Alignment(xalign=0.5, yalign=0.5, xscale=1, yscale=0)
        al.set_size_request(-1, 10)
        al.add(hsep)
        self.grid.attach(al, 0, self.row.get(), 2, 1)
        self.row.increase()

    def _save_widget(self, fn: str, widget, widget_type: str, **kwargs) -> None:
        setattr(self, "%s_widget" % fn, widget)
        setattr(self, "%s_widget_type" % fn, widget_type)
        for k, v in kwargs.items():
            setattr(self, f"{fn}_{k}", v)

    def get_widget(self, fn):
        return getattr(self, "%s_widget" % fn)

    def get_widget_options(self, fn):
        return getattr(self, "%s_options" % fn)

    def bool_cb(self, text: str, option_name: str, tooltip_text="", link="") -> Gtk.Switch:
        self.attach_label(_(text), _(tooltip_text), link)
        fn = option_name.replace("-", "_")
        value = getattr(self.options, fn)
        cb = switch()
        active = str(value).lower() not in FALSE_OPTIONS
        cb.set_active(active)
        al = xal(cb, xalign=0)
        self.grid.attach(al, 1, self.row.get(), 1, 1)
        self._save_widget(fn, cb, "bool", values=[value if not active else False, value if active else True])
        self.widgets.append(option_name)
        self.row.increase()
        return cb

    def radio_cb_auto(self, text: str, option_name: str, tooltip_text="", link="") -> Gtk.RadioButton:
        return self.radio_cb(text, option_name, tooltip_text, link, {
            "yes": TRUE_OPTIONS,
            "no": FALSE_OPTIONS,
            "auto": ("auto", "", None),
        })

    def radio_cb(self, text: str, option_name: str, tooltip_text="", link="", options=None) -> Gtk.RadioButton:
        self.attach_label(_(text), _(tooltip_text), link)
        fn = option_name.replace("-", "_")
        widget_base_name = "%s_widget" % fn
        self.widgets.append(option_name)
        value = getattr(self.options, fn)
        hbox = Gtk.HBox(homogeneous=True, spacing=10)
        i = 0
        sibling = None
        btns = []
        saved_options = {}
        for option, match in options.items():
            btn = Gtk.RadioButton.new_with_label_from_widget(sibling, _(option))
            hbox.add(btn)
            setattr(self, f"{widget_base_name}_{option}", btn)
            saved_match = match
            matched = value in match or str(value).lower() in match
            btn.set_active(matched)
            if matched:
                # ensure we save the current value first,
                # so that's what we will set as value when retrieving the form values:
                saved_match = [value] + list(match)
            if i == 0:
                sibling = btn
            i += 1
            saved_options[option] = saved_match
            btns.append(btn)
        self._save_widget(fn, btns, "radio", options=saved_options)
        self.grid.attach(hbox, 1, self.row.get(), 1, 1)
        self.row.increase()
        return btns

    def combo(self, text: str, option_name: str, options: dict, link="") -> Gtk.ComboBoxText:
        self.attach_label(_(text), "", link)
        fn = option_name.replace("-", "_")
        value = getattr(self.options, fn)
        c = Gtk.ComboBoxText()
        index = -1
        for i, (v, vlabel) in enumerate(options.items()):
            c.append_text(_(str(vlabel)))
            if index < 0 or v == value:
                index = i
        if index >= 0:
            c.set_active(index)
        al = Gtk.Alignment(xalign=0, yalign=0.5, xscale=0.0, yscale=1.0)
        al.add(c)
        self.grid.attach(al, 1, self.row.get(), 1, 1)
        self._save_widget(fn, c, "combo", options=options)
        self.widgets.append(option_name)
        self.row.increase()
        return c

    def scale(self, text: str, option_name: str, minv=0, maxv=100, marks=None) -> Gtk.Scale:
        self.attach_label(_(text))
        fn = option_name.replace("-", "_")
        value = getattr(self.options, fn)
        c = Gtk.Scale.new(orientation=Gtk.Orientation.HORIZONTAL)
        c.set_range(minv, maxv)
        c.set_draw_value(True)
        c.set_digits(0)
        c.set_hexpand(True)
        c.set_value(value or 0)
        c.set_valign(Gtk.Align.START)
        if marks:
            for v, mtext in marks.items():
                c.add_mark(v, Gtk.PositionType.BOTTOM, _(mtext))
        self.grid.attach(c, 1, self.row.get(), 1, 1)
        self._save_widget(fn, c, "scale")
        self.widgets.append(option_name)
        self.row.increase()
        return c

    def set_value_from_widgets(self) -> None:
        for option_name in self.widgets:
            self.set_value_from_widget(option_name)

    def set_value_from_widget(self, option_name: str) -> None:
        fn = option_name.replace("-", "_")
        widget_type = getattr(self, "%s_widget_type" % fn)
        if widget_type == "bool":
            values = self.valuesfromswitch(option_name)
        elif widget_type == "radio":
            values = self.valuesfromradio(option_name)
        elif widget_type == "combo":
            values = self.valuesfromcombo(option_name)
        elif widget_type == "scale":
            values = self.valuesfromscale(option_name)
        else:
            log.warn("unknown widget type '%s'", widget_type)
            return
        if len(values) != 1 or values[0] != UNSET:
            current_value = getattr(self.options, fn)
            for v in values:
                if current_value == v:
                    # unchanged
                    return
            # pick the first one:
            value = values[0]
            log.info("changed: %s=%r (%s) - was %r (%s)", fn, value, type(value), current_value, type(current_value))
            setattr(self.options, fn, value)

    def valuesfromswitch(self, option_name: str) -> tuple:
        fn = option_name.replace("-", "_")
        widget = self.get_widget(fn)
        values = getattr(self, "%s_values" % fn)
        value = values[int(widget.get_active())]
        return (value,)

    def valuesfromradio(self, option_name: str) -> tuple:
        fn = option_name.replace("-", "_")
        options = self.get_widget_options(fn)
        widget_base_name = "%s_widget" % fn
        for text, match in options.items():
            btn = getattr(self, "%s_%s" % (widget_base_name, text))
            if btn.get_active():
                return tuple(match)
        return (UNSET,)

    def valuesfromcombo(self, option_name: str) -> tuple:
        fn = option_name.replace("-", "_")
        widget = self.get_widget(fn)
        options = self.get_widget_options(fn)
        value = widget.get_active_text()
        for k, v in options.items():
            if _(str(v)) == value:
                return (k,)
        return (UNSET,)

    def valuesfromscale(self, option_name: str) -> tuple[int]:
        fn = option_name.replace("-", "_")
        widget = self.get_widget(fn)
        return (int(widget.get_value()),)

    def attach_label(self, text: str, tooltip_text="", link="") -> None:
        lbl = label(text, tooltip=tooltip_text)
        add_style_class(lbl, "xpra-heading", "xpra-cell")
        lbl.set_margin_start(5)
        lbl.set_margin_top(5)
        lbl.set_margin_end(5)
        lbl.set_margin_bottom(5)
        hbox = Gtk.HBox(homogeneous=False, spacing=0)
        hbox.pack_start(xal(lbl), True, True)
        if link:
            help_btn = link_btn(link, _("About %s") % text)
            hbox.pack_start(help_btn, False)
        self.grid.attach(hbox, 0, int(self.row), 1, 1)


class FeaturesWindow(SessionOptions):
    def __init__(self, *args):
        super().__init__("Session Features", "features.png", *args)

    def populate_form(self) -> None:
        btn = link_btn("https://xpra-org.github.io/xpra/Features/",
                       "Open Features Documentation", icon_name="")
        self.vbox.pack_start(btn, expand=True, fill=False, padding=20)
        self.bool_cb("Splash Screen", "splash", "Show a splash screen during startup")
        self.bool_cb("Read only", "readonly", "Mouse and keyboard events will be ignored")
        self.radio_cb("Border", "border", "Show a colored border around xpra windows to differentiate them", "", {
            "auto": ("auto,5:off", "auto"),
            "none": FALSE_OPTIONS,
            "blue": ("blue",),
            "red": ("red",),
            "green": ("green",)
        })
        self.radio_cb("Header Bar", "headerbar", "", "", {
            "auto": ["auto"] + list(TRUE_OPTIONS),
            "no": FALSE_OPTIONS,
            "force": ("force",),
        })
        self.sep()
        # "https://xpra-org.github.io/xpra/Features/Notifications.html")
        self.bool_cb("Xpra's System Tray", "tray")
        self.bool_cb("Forward System Trays", "system-tray")
        self.bool_cb("Notifications", "notifications")
        # "https://xpra-org.github.io/xpra/Features/System-Tray.html")
        # self.bool_cb("Cursors", "cursors")
        # self.bool_cb("Bell", "bell")
        self.bool_cb("Modal Windows", "modal-windows")
        self.sep()
        # "https://xpra-org.github.io/xpra/Features/Image-Depth.html")
        self.combo("Mouse Wheel", "mousewheel", {
            "on": "on",
            "no": "disabled",
            "invert-x": "invert X axis",
            "invert-y": "invert Y axis",
            "invert-z": "invert Z axis",
            "invert-all": "invert all axes",
        })
        self.combo("Clipboard", "clipboard-direction", {
            "both": "enabled",
            "to-server": "to server only",
            "to-client": "to client only",
            "disabled": "disabled",
        })
        if is_X11():
            self.bool_cb("XSettings", "xsettings")
        self.vbox.show_all()


class NetworkWindow(SessionOptions):
    def __init__(self, *args):
        super().__init__("Network Options", "connect.png", *args)

    def populate_form(self) -> None:
        btn = link_btn("https://xpra-org.github.io/xpra/Network/",
                       "Open Network Documentation", icon_name="")
        self.vbox.pack_start(btn, expand=True, fill=False, padding=20)
        # "https://xpra-org.github.io/xpra/Network/Multicast-DNS.html")
        # `sync` is a client-side option which implies sharing:
        self.radio_cb("Session Sharing", "sharing", options={
            "yes": tuple(TRUE_OPTIONS) + ("sync", ),
            "no": FALSE_OPTIONS,
            "auto": ("auto", "", None),
        })
        self.radio_cb_auto("Session Lock", "lock", "Prevent sessions from being taken over by new clients")
        self.sep()
        self.bool_cb("Multicast DNS", "mdns", "Publish the session via mDNS")
        self.bool_cb("Bandwidth Detection", "bandwidth-detection", "Automatically detect runtime bandwidth limits")
        bwoptions = {
            "auto": "Auto",
        }
        for bwlimit in BANDWIDTH_MENU_OPTIONS:
            if bwlimit <= 0:
                s = "None"
            elif bwlimit >= 10 * 1000 * 1000:
                s = "%iMbps" % (bwlimit // (1000 * 1000))
            else:
                s = "%sbps" % std_unit_dec(bwlimit)
            bwoptions[bwlimit] = s
        self.combo("Bandwidth Limit", "bandwidth-limit", bwoptions)
        # ssl options
        # ssh=paramiko | asyncssh | plink
        # exit-ssh
        # Remote Logging
        # open-files
        # open-url
        # file-size-limit
        self.vbox.show_all()


class DisplayWindow(SessionOptions):
    def __init__(self, *args):
        super().__init__("Display Settings", "display.png", *args)

    def populate_form(self) -> None:
        btn = link_btn("https://xpra-org.github.io/xpra/Features/Display.html",
                       "Open Display Documentation", icon_name="")
        self.vbox.pack_start(btn, expand=True, fill=False, padding=20)

        pixel_depths: dict[int, str] = {0: "auto"}
        if self.run_mode == "shadow":
            pixel_depths[8] = "8"
        for pd in (16, 24, 30, 32):
            pixel_depths[pd] = str(pd)
        if self.run_mode == "desktop":
            size_options: dict[str, str] = {
                "auto": "auto",
            }
            for size in SCREEN_SIZES:
                try:
                    w, h = size.split("x")
                    size_options[f"{w}x{h}"] = f"{w} x {h}"
                except (TypeError, ValueError, IndexError):
                    size_options[size] = size
            self.combo("Screen Size", "resize-display", size_options)
        self.combo("Pixel Depth", "pixel-depth", pixel_depths)
        self.combo("DPI", "dpi", {
            0: "auto",
            72: "72",
            96: "96",
            144: "144",
            192: "192",
        })
        self.combo("Desktop Scaling", "desktop-scaling", {
            "on": "auto",
            "no": "disabled",
            "50%": "50%",
            "100%": "100%",
            "150%": "150%",
            "200%": "200%",
        })
        self.radio_cb("OpenGL Acceleration", "opengl", "", "", {
            "probe": "probe",
            "auto": ["auto"] + list(TRUE_OPTIONS),
            "no": FALSE_OPTIONS,
            "force": ("force",),
        })
        self.vbox.show_all()


class EncodingWindow(SessionOptions):
    def __init__(self, *args):
        super().__init__("Picture Encoding", "encoding.png", *args)

    def populate_form(self) -> None:
        btn = link_btn("https://xpra-org.github.io/xpra/Usage/Encodings.html",
                       "Open Encodings Documentation", icon_name="")
        self.vbox.pack_start(btn, expand=True, fill=False, padding=20)

        self.scale("Minimum Quality", "min-quality", marks={
            0: "Very Low",
            30: "Low",
            50: "Medium",
            75: "High",
            100: "Lossless",
        })
        self.scale("Minimum Speed", "min-speed", marks={
            0: "Low Bandwidth",
            100: "Low Latency",
        })
        self.sep()
        self.combo("Auto-refresh", "auto-refresh-delay", {
            0: "disabled",
            0.1: "fast",
            0.15: "normal",
            0.5: "slow",
        })
        from xpra.client.subsystem.encoding import get_core_encodings
        encodings = ["auto", "rgb"] + list(get_core_encodings())
        encodings.remove("rgb24")
        encodings.remove("rgb32")
        if "grayscale" not in encodings:
            encodings.append("grayscale")
        from xpra.codecs.loader import get_encoding_name
        encoding_options = {encoding: get_encoding_name(encoding) for encoding in encodings}
        self.combo("Encoding", "encoding", encoding_options)
        self.vbox.show_all()


class KeyboardWindow(SessionOptions):
    def __init__(self, *args):
        super().__init__("Keyboard Options", "keyboard.png", *args)

    def populate_form(self) -> None:
        btn = link_btn("https://xpra-org.github.io/xpra/Features/Keyboard.html",
                       "Open Keyboard Documentation", icon_name="")
        self.vbox.pack_start(btn, expand=True, fill=False, padding=20)

        from xpra.platform.keyboard import Keyboard
        kbd = Keyboard()  # pylint: disable=not-callable
        layouts = {
            "": "auto",
        }
        x11_layouts: dict[str, str] = kbd.get_all_x11_layouts()
        # many layouts can have the same name (ie: "English"),
        # only keep the first one that provides it:
        names = set()
        for x11_layout, name in x11_layouts.items():
            if x11_layout and name and (name not in names):
                layouts[x11_layout] = name
                names.add(name)
        self.combo("Keyboard Layout", "keyboard-layout", layouts)
        self.bool_cb("State Synchronization", "keyboard-sync")
        self.bool_cb("Raw Mode", "keyboard-raw")
        self.combo("Input Method", "input-method", {
            "auto": "auto",
            "none": "default",
            "keep": "unchanged",
            "xim": "xim",
            "IBus": "IBus",
            "SCIM": "SCIM",
            "uim": "uim",
        })
        self.combo("Shortcut Modifiers", "shortcut-modifiers", {
            "auto": "auto",
            "shift + control": "Shift+Control",
            "control + alt": "Control+Alt",
            "shift + alt": "Shift+Alt",
        })
        self.vbox.show_all()


class AudioWindow(SessionOptions):
    def __init__(self, *args):
        super().__init__("Audio Options", "speaker.png", *args)

    def populate_form(self) -> None:
        btn = link_btn("https://xpra-org.github.io/xpra/Features/Audio.html",
                       "Open Audio Documentation", icon_name="")
        self.vbox.pack_start(btn, expand=True, fill=False, padding=20)

        self.radio_cb("Speaker", "speaker", "", "", {
            "on": TRUE_OPTIONS,
            "off": FALSE_OPTIONS,
            "disabled": ("disabled",),
        })
        self.sep()
        self.radio_cb("Microphone", "microphone", "", "", {
            "on": TRUE_OPTIONS,
            "off": FALSE_OPTIONS,
            "disabled": ("disabled",),
        })
        self.sep()
        self.bool_cb("AV Sync", "av-sync")
        self.vbox.show_all()


class WebcamWindow(SessionOptions):
    def __init__(self, *args):
        super().__init__("Webcam", "webcam.png", *args)

    def populate_form(self) -> None:
        btn = link_btn("https://xpra-org.github.io/xpra/Features/Webcam.html",
                       "Open Webcam Documentation", icon_name="")
        self.vbox.pack_start(btn, expand=True, fill=False, padding=20)

        cb = self.bool_cb("Webcam", "webcam")
        if OSX or WIN32:
            cb.set_sensitive(False)
            cb.set_active(False)
            self.grid.attach(label(_("Webcam forwarding is not supported on %s") % platform_name()),
                             0, self.row.increase(), 2, 1)
        self.vbox.show_all()


class PrintingWindow(SessionOptions):
    def __init__(self, *args):
        super().__init__("Printer", "printer.png", *args)

    def populate_form(self) -> None:
        btn = link_btn("https://xpra-org.github.io/xpra/Features/Printing.html",
                       "Open Printing Documentation", icon_name="")
        self.vbox.pack_start(btn, expand=True, fill=False, padding=20)

        self.radio_cb_auto("Printing", "printing")
        self.vbox.show_all()


def main(options=None) -> int:  # pragma: no cover
    # pylint: disable=import-outside-toplevel
    from xpra.platform import program_context
    from xpra.log import enable_color
    from xpra.platform.gui import init, ready
    from xpra.gtk.util import init_display_source, quit_on_signals, gtk_main
    with program_context("xpra-start-gui", _("Xpra Start GUI")):
        enable_color()
        init_display_source(False)
        init()
        quit_on_signals("start-gui")
        gui = StartSession(options)
        register_os_signals(gui.app_signal)
        ready()
        gui.session_toggled()
        if WIN32 or OSX:
            gui.remote_btn.set_active(True)
        gui.show()
        gui.present()
        gtk_main()
        log("do_main() gui.exit_code=%s", gui.exit_code)
        return gui.exit_code


if __name__ == "__main__":  # pragma: no cover
    r = main()
    sys.exit(r)
