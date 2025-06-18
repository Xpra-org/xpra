#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2009 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# pylint: disable=no-member

""" launcher.py

This was meant to be a simple GUI for starting the xpra client.
Then it morphed into something quite messy. Sorry.

"""

import os.path
import sys
import traceback
from typing import Any
from collections.abc import Callable

from xpra.scripts.config import read_config, make_defaults_struct, validate_config, save_config
from xpra.gtk.signals import register_os_signals
from xpra.gtk.window import add_close_accel
from xpra.gtk.widget import (
    scaled_image, imagebutton, label, choose_file, modify_fg,
    set_widget_bg_color, set_widget_fg_color, red, black,
)
from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.util.str_fn import csv, repr_ellipsized
from xpra.os_util import WIN32, OSX, gi_import
from xpra.util.env import IgnoreWarningsContext
from xpra.net.common import DEFAULT_PORT
from xpra.util.thread import start_thread
from xpra.gtk.dialogs.about import about
from xpra.gtk.dialogs.util import hb_button
from xpra.scripts.main import (
    connect_to, make_client, bypass_no_gtk,
    configure_network, configure_env, configure_logging,
)
from xpra.common import noop
from xpra.scripts.parsing import is_local, get_ssh_args, parse_ssh_option, get_ssh_proxy_args, get_ssl_options
from xpra.exit_codes import RETRY_EXIT_CODES, ExitCode, ExitValue, exit_str
from xpra.platform.info import get_username
from xpra.log import Logger, enable_debug_for

log = Logger("launcher")

Gtk = gi_import("Gtk")
GdkPixbuf = gi_import("GdkPixbuf")
GLib = gi_import("GLib")

MODE_NESTED_SSH = "ssh -> ssh"
MODE_SSH = "ssh"
MODE_TCP = "tcp"
MODE_SSL = "ssl"
MODE_WS = "ws"
MODE_WSS = "wss"
MODE_QUIC = "quic"

# what we save in the config file:
SAVED_FIELDS = [
    "username", "password", "host", "port", "mode", "ssh_port", "path",
    "encoding", "quality", "min-quality", "speed", "min-speed",
    "proxy_port", "proxy_username", "proxy_key", "proxy_password",
    "proxy_host",
    "autoconnect",
]

# options not normally found in xpra config file
# but which can be present in a launcher config:
LAUNCHER_OPTION_TYPES = {
    "host": str,
    "port": int,
    "username": str,
    "password": str,
    "mode": str,
    "path": str,
    "autoconnect": bool,
    "ssh_port": int,
    "proxy_host": str,
    "proxy_port": int,
    "proxy_username": str,
    "proxy_password": str,
    "proxy_key": str,
}
LAUNCHER_DEFAULTS = {
    "host": "",
    "port": -1,
    "username": get_username(),
    "password": "",
    "mode": MODE_TCP,  # tcp,ssh,..
    "path": "",
    "autoconnect": False,
    "ssh_port": 22,
    "proxy_host": "",
    "proxy_port": 22,
    "proxy_username": get_username(),
    "proxy_password": "",
    "proxy_key": "",
}


def get_active_item_index(optionmenu) -> int:
    menu = optionmenu.get_popup()
    for i, x in enumerate(menu.get_children()):
        if hasattr(x, "get_active") and x.get_active():
            return i
    return -1


def set_history_from_active(optionmenu) -> None:
    # Used for MenuButton combo:
    # sets the first active menu entry as the "history" value (the selected item)
    i = get_active_item_index(optionmenu)
    if i > 0:
        optionmenu.set_history(i)


def has_mdns() -> bool:
    try:
        # pylint: disable=import-outside-toplevel
        from xpra.net.mdns import get_listener_class
        lc = get_listener_class()
        log("mdns listener class: %s", lc)
        if lc:
            return True
    except ImportError as e:
        log("no mdns support: %s", e)
    return False


def get_connection_modes() -> list[str]:
    modes = [MODE_SSH, MODE_NESTED_SSH]
    try:
        import ssl
        assert ssl
        modes.append(MODE_SSL)
        modes.append(MODE_QUIC)
    except ImportError:
        pass
    # assume crypto is available
    try:
        from xpra.net.crypto import get_modes
        for mode in get_modes():
            modes.append(f"tcp + aes-{mode.lower()}")
    except ImportError:
        pass
    modes.append(MODE_TCP)
    modes.append(MODE_WS)
    modes.append(MODE_WSS)
    return modes


def image_button(text="", tooltip="", icon_pixbuf=None, clicked_cb=None) -> Gtk.Image:
    icon = Gtk.Image()
    icon.set_from_pixbuf(icon_pixbuf)
    return imagebutton(text, icon, tooltip, clicked_cb, icon_size=None)


def button(tooltip, icon_name, callback) -> Gtk.Button:
    btn = Gtk.Button()
    theme = Gtk.IconTheme.get_default()
    try:
        pixbuf = theme.load_icon(icon_name, Gtk.IconSize.BUTTON, Gtk.IconLookupFlags.USE_BUILTIN)
    except Exception:
        pixbuf = None
    if not pixbuf:
        pixbuf = get_icon_pixbuf(f"{icon_name}.png")
        if pixbuf:
            with IgnoreWarningsContext():
                for size in (16, 32, 48):
                    scaled = pixbuf.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)
                    Gtk.IconTheme.add_builtin_icon(icon_name, size, scaled)
            try:
                builtin_reload = theme.load_icon(icon_name, Gtk.IconSize.BUTTON, Gtk.IconLookupFlags.USE_BUILTIN)
            except Exception:
                log("button: failed to load icon after adding to builtins", exc_info=True)
                size = 32
                pixbuf = pixbuf.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)
            else:
                pixbuf = builtin_reload
    if pixbuf:
        image = Gtk.Image.new_from_pixbuf(pixbuf)
        btn.add(image)
    btn.set_tooltip_text(tooltip)

    def clicked(*_args) -> None:
        callback()

    btn.connect("clicked", clicked)
    return btn


def get_launcher_validation() -> dict:
    # TODO: since "mode" is not part of global options
    # this validation should be injected from the launcher instead
    def validate_in_list(x, options) -> str:
        if x in options:
            return ""
        return "must be in " + csv(options)

    modes = get_connection_modes()
    return {"mode": lambda x: validate_in_list(x, modes)}


def accel_close(*args) -> None:
    log("accel_close%s", args)
    Gtk.main_quit()


class ApplicationWindow:

    def __init__(self):
        # Default connection options
        self.config = make_defaults_struct(extras_defaults=LAUNCHER_DEFAULTS,
                                           extras_types=LAUNCHER_OPTION_TYPES,
                                           extras_validation=get_launcher_validation())
        self.parse_ssh()
        # TODO: the fixup does not belong here?
        from xpra.scripts.main import fixup_options
        fixup_options(self.config)
        # what we save by default:
        self.config_keys = set(SAVED_FIELDS)
        self.client = None
        self.exit_launcher = False
        self.exit_code = None
        self.current_error = None

    def parse_ssh(self) -> None:
        ssh_cmd = parse_ssh_option(self.config.ssh)[0].strip().lower()
        self.is_putty = ssh_cmd.endswith("plink") or ssh_cmd.endswith("plink.exe")
        self.is_paramiko = ssh_cmd.startswith("paramiko")

    def create_window_with_config(self) -> None:
        self.do_create_window()
        self.update_gui_from_config()

    def do_create_window(self) -> None:
        self.window = Gtk.Window()
        self.window.set_border_width(20)
        self.window.connect("delete-event", self.destroy)
        self.window.set_default_size(400, 260)
        self.window.set_title("Xpra Launcher")
        self.window.set_position(Gtk.WindowPosition.CENTER)
        with IgnoreWarningsContext():
            self.window.set_wmclass("xpra-launcher-gui", "Xpra-Launcher-GUI")
        add_close_accel(self.window, accel_close)
        icon = get_icon_pixbuf("connect.png")
        if icon:
            self.window.set_icon(icon)

        hb = Gtk.HeaderBar()
        hb.set_show_close_button(True)
        hb.props.title = "Session Launcher"
        self.window.set_titlebar(hb)

        def show_about(*_args) -> None:
            about(parent=self.window)

        hb.add(hb_button("About", "help-about", show_about))
        self.bug_tool = None

        def bug(*_args) -> None:
            if self.bug_tool is None:
                from xpra.gtk.dialogs.bug_report import BugReport
                self.bug_tool = BugReport()
                self.bug_tool.init(show_about=False)
            self.bug_tool.show()

        hb.add(hb_button("Bug Report", "bugs", bug))
        if has_mdns():
            self.mdns_gui = None

            def mdns(*_args) -> None:
                if self.mdns_gui is None:
                    from xpra.gtk.dialogs.mdns_gui import mdns_sessions
                    self.mdns_gui = mdns_sessions(self.config)

                    def close_mdns() -> None:
                        mdns_gui = self.mdns_gui
                        if mdns_gui:
                            self.mdns_gui = None
                            mdns_gui.close()

                    self.mdns_gui.do_quit = close_mdns
                else:
                    self.mdns_gui.present()

            hb.add(hb_button("Browse Sessions", "mdns", mdns))
        hb.show_all()

        vbox = Gtk.VBox(homogeneous=False, spacing=0)
        vbox.set_spacing(15)

        # Title
        vbox.pack_start(label("Connect to xpra server", font="sans 14"))

        # Mode:
        hbox = Gtk.HBox(homogeneous=False, spacing=5)
        self.mode_combo = Gtk.ComboBoxText()
        for x in get_connection_modes():
            self.mode_combo.append_text(x.upper())
        self.mode_combo.connect("changed", self.mode_changed)
        hbox.pack_start(label("Mode: "), False, False)
        hbox.pack_start(self.mode_combo, False, False)
        align_hbox = Gtk.Alignment(xalign=0.5)
        align_hbox.add(hbox)
        vbox.pack_start(align_hbox)

        # Username@Host:Port (ssh -> ssh, proxy)
        vbox_proxy = Gtk.VBox(homogeneous=False, spacing=15)
        hbox = Gtk.HBox(homogeneous=False, spacing=5)
        self.proxy_vbox = vbox_proxy
        self.proxy_username_entry = Gtk.Entry()
        self.proxy_username_entry.set_max_length(128)
        self.proxy_username_entry.set_width_chars(16)
        self.proxy_username_entry.connect("changed", self.validate)
        self.proxy_username_entry.connect("activate", self.connect_clicked)
        self.proxy_username_entry.set_tooltip_text("username")
        self.proxy_host_entry = Gtk.Entry()
        self.proxy_host_entry.set_max_length(128)
        self.proxy_host_entry.set_width_chars(24)
        self.proxy_host_entry.connect("changed", self.validate)
        self.proxy_host_entry.connect("activate", self.connect_clicked)
        self.proxy_host_entry.set_tooltip_text("hostname")
        self.proxy_port_entry = Gtk.Entry()
        self.proxy_port_entry.set_max_length(5)
        self.proxy_port_entry.set_width_chars(5)
        self.proxy_port_entry.connect("changed", self.validate)
        self.proxy_port_entry.connect("activate", self.connect_clicked)
        self.proxy_port_entry.set_tooltip_text("SSH port")
        hbox.pack_start(label("Proxy: "), False, False)
        hbox.pack_start(self.proxy_username_entry, True, True)
        hbox.pack_start(label("@"), False, False)
        hbox.pack_start(self.proxy_host_entry, True, True)
        hbox.pack_start(self.proxy_port_entry, False, False)
        vbox_proxy.pack_start(hbox)

        # Password
        hbox = Gtk.HBox(homogeneous=False, spacing=5)
        self.proxy_password_hbox = hbox
        self.proxy_password_entry = Gtk.Entry()
        self.proxy_password_entry.set_max_length(128)
        self.proxy_password_entry.set_width_chars(30)
        self.proxy_password_entry.set_text("")
        self.proxy_password_entry.set_visibility(False)
        self.proxy_password_entry.connect("changed", self.password_ok)
        self.proxy_password_entry.connect("changed", self.validate)
        self.proxy_password_entry.connect("activate", self.connect_clicked)
        hbox.pack_start(label("Proxy Password"), False, False)
        hbox.pack_start(self.proxy_password_entry, True, True)
        vbox_proxy.pack_start(hbox)

        # Private key
        hbox = Gtk.HBox(homogeneous=False, spacing=5)
        self.pkey_hbox = hbox
        self.proxy_key_label = label("Proxy private key path (PPK):")
        self.proxy_key_entry = Gtk.Entry()
        self.proxy_key_browse = Gtk.Button(label="Browse")
        self.proxy_key_browse.connect("clicked", self.proxy_key_browse_clicked)
        hbox.pack_start(self.proxy_key_label, False, False)
        hbox.pack_start(self.proxy_key_entry, True, True)
        hbox.pack_start(self.proxy_key_browse, False, False)
        vbox_proxy.pack_start(hbox)

        # Check boxes
        hbox = Gtk.HBox(homogeneous=False, spacing=5)
        self.check_boxes_hbox = hbox
        self.password_scb = Gtk.CheckButton(label="Server password same as proxy")
        self.password_scb.set_mode(True)
        self.password_scb.set_active(True)
        self.password_scb.connect("toggled", self.validate)
        align_password_scb = Gtk.Alignment(xalign=1.0)
        align_password_scb.add(self.password_scb)
        self.username_scb = Gtk.CheckButton(label="Server username same as proxy")
        self.username_scb.set_mode(True)
        self.username_scb.set_active(True)
        self.username_scb.connect("toggled", self.validate)
        align_username_scb = Gtk.Alignment(xalign=0.0)
        align_username_scb.add(self.username_scb)
        hbox.pack_start(align_username_scb, True, True)
        hbox.pack_start(align_password_scb, True, True)
        vbox_proxy.pack_start(hbox)

        # condiditonal stuff that goes away for "normal" ssh
        vbox.pack_start(vbox_proxy)

        # Username@Host:Port (main)
        hbox = Gtk.HBox(homogeneous=False, spacing=5)
        self.username_entry = Gtk.Entry()
        self.username_entry.set_max_length(128)
        self.username_entry.set_width_chars(16)
        self.username_entry.connect("changed", self.validate)
        self.username_entry.connect("activate", self.connect_clicked)
        self.username_entry.set_tooltip_text("server username")
        self.host_entry = Gtk.Entry()
        self.host_entry.set_max_length(128)
        self.host_entry.set_width_chars(24)
        self.host_entry.connect("changed", self.validate)
        self.host_entry.connect("activate", self.connect_clicked)
        self.host_entry.set_tooltip_text("server hostname or IP address")
        self.ssh_port_entry = Gtk.Entry()
        self.ssh_port_entry.set_max_length(5)
        self.ssh_port_entry.set_width_chars(5)
        self.ssh_port_entry.connect("changed", self.validate)
        self.ssh_port_entry.connect("activate", self.connect_clicked)
        self.ssh_port_entry.set_tooltip_text("SSH port")
        self.port_entry = Gtk.Entry()
        self.port_entry.set_max_length(5)
        self.port_entry.set_width_chars(5)
        self.port_entry.connect("changed", self.validate)
        self.port_entry.connect("activate", self.connect_clicked)
        self.port_entry.set_tooltip_text("port/display")
        self.path_entry = Gtk.Entry()
        self.path_entry.set_max_length(128)
        self.path_entry.set_width_chars(5)
        self.path_entry.connect("activate", self.connect_clicked)
        self.path_entry.set_tooltip_text("request path")
        hbox.pack_start(label("Server:"), False, False)
        hbox.pack_start(self.username_entry, True, True)
        hbox.pack_start(label("@"), False, False)
        hbox.pack_start(self.host_entry, True, True)
        hbox.pack_start(self.ssh_port_entry, False, False)
        hbox.pack_start(label(":"), False, False)
        hbox.pack_start(self.port_entry, False, False)
        hbox.pack_start(label("/"), False, False)
        hbox.pack_start(self.path_entry, False, False)
        vbox.pack_start(hbox)

        # Password
        hbox = Gtk.HBox(homogeneous=False, spacing=5)
        self.password_hbox = hbox
        self.password_entry = Gtk.Entry()
        self.password_entry.set_max_length(128)
        self.password_entry.set_width_chars(30)
        self.password_entry.set_text("")
        self.password_entry.set_visibility(False)
        self.password_entry.connect("changed", self.password_ok)
        self.password_entry.connect("changed", self.validate)
        self.password_entry.connect("activate", self.connect_clicked)
        hbox.pack_start(label("Server Password:"), False, False)
        hbox.pack_start(self.password_entry, True, True)
        vbox.pack_start(hbox)

        # strict host key check for SSL and SSH
        hbox = Gtk.HBox(homogeneous=False, spacing=5)
        self.nostrict_host_check = Gtk.CheckButton(label="Disable Strict Host Key Check")
        self.nostrict_host_check.set_active(False)
        al = Gtk.Alignment(xalign=0.5, yalign=0.5, xscale=0.0, yscale=0)
        al.add(self.nostrict_host_check)
        hbox.pack_start(al)
        vbox.pack_start(hbox)

        # auto-connect
        hbox = Gtk.HBox(homogeneous=False, spacing=5)
        self.autoconnect = Gtk.CheckButton(label="Auto-connect")
        self.autoconnect.set_active(False)
        self.autoconnect.set_tooltip_text("Connect without opening this launcher when opening the session file")
        al = Gtk.Alignment(xalign=0.5, yalign=0.5, xscale=0.0, yscale=0)
        al.add(self.autoconnect)
        hbox.pack_start(al)
        vbox.pack_start(hbox)

        # Info Label
        self.info = label()
        self.info.set_line_wrap(True)
        self.info.set_size_request(360, -1)
        modify_fg(self.info, red)
        vbox.pack_start(self.info)

        # Buttons:
        hbox = Gtk.HBox(homogeneous=False, spacing=20)
        vbox.pack_start(hbox)
        # Save:
        self.save_btn = Gtk.Button(label="Save")
        self.save_btn.set_tooltip_text("Save settings to a session file")
        self.save_btn.connect("clicked", self.save_clicked)
        hbox.pack_start(self.save_btn)
        # Load:
        self.load_btn = Gtk.Button(label="Load")
        self.load_btn.set_tooltip_text("Load settings from a session file")
        self.load_btn.connect("clicked", self.load_clicked)
        hbox.pack_start(self.load_btn)
        # Connect button:
        self.connect_btn = Gtk.Button(label="Connect")
        self.connect_btn.connect("clicked", self.connect_clicked)
        connect_icon = get_icon_pixbuf("retry.png")
        if connect_icon:
            self.connect_btn.set_image(scaled_image(connect_icon, 24))
        hbox.pack_start(self.connect_btn)

        vbox.show_all()
        self.window.vbox = vbox
        self.window.add(vbox)

    def validate(self, *args) -> list:
        mode = self.mode_combo.get_active_text().lower()
        ssh = mode == MODE_SSH
        sshtossh = mode == MODE_NESTED_SSH
        errs = []
        host = self.host_entry.get_text()
        errs.append((self.host_entry, not bool(host), "specify the host"))
        if ssh or sshtossh:
            # validate ssh port:
            ssh_port = self.ssh_port_entry.get_text()
            try:
                ssh_port = int(ssh_port)
            except ValueError:
                ssh_port = -1
            errs.append((self.ssh_port_entry,
                         ssh_port < 0 or ssh_port >= 2 ** 16,
                         "invalid SSH port number"))
        if sshtossh:
            # validate ssh port:
            proxy_port = self.proxy_port_entry.get_text()
            try:
                proxy_port = int(proxy_port)
            except ValueError:
                proxy_port = -1
            errs.append((self.proxy_port_entry,
                         proxy_port < 0 or proxy_port >= 2 ** 16,
                         "invalid SSH port number"))
        port = self.port_entry.get_text()
        if sshtossh:
            if self.password_scb.get_active():
                self.password_entry.set_sensitive(False)
                self.password_entry.set_text(self.proxy_password_entry.get_text())
            else:
                self.password_entry.set_sensitive(True)
            if self.username_scb.get_active():
                self.username_entry.set_sensitive(False)
                self.username_entry.set_text(self.proxy_username_entry.get_text())
            else:
                self.username_entry.set_sensitive(True)
            errs.append((self.proxy_host_entry,
                         not bool(self.proxy_host_entry.get_text()),
                         "specify the proxy host"))
        # check username *after* the checkbox action
        if ssh or sshtossh:
            errs.append((self.username_entry,
                         not bool(self.username_entry.get_text()),
                         "specify username"))
        if sshtossh:
            errs.append((self.proxy_username_entry,
                         not bool(self.proxy_username_entry.get_text()),
                         "specify proxy username"))
        if ssh or sshtossh and not port:
            port = 0  # port optional with ssh
        else:
            try:
                port = int(port)
            except (ValueError, TypeError):
                port = -1
        errs.append((self.port_entry, port < 0 or port >= 2 ** 16, "invalid port number"))
        err_text = []
        for w, e, text in errs:
            set_widget_bg_color(w, e)
            if e:
                err_text.append(text)
        log(f"validate({args}) err_text={err_text}, errs={errs}")
        self.set_info_text(csv(err_text), bool(err_text))
        self.connect_btn.set_sensitive(len(err_text) == 0)
        return errs

    def show(self) -> None:
        self.window.show()
        self.window.present()
        self.connect_btn.grab_focus()

    def run(self) -> ExitValue:
        Gtk.main()
        return self.exit_code or 0

    def mode_changed(self, *_args) -> None:
        mode = self.mode_combo.get_active_text().lower()
        ssh = mode == MODE_SSH
        sshtossh = mode == MODE_NESTED_SSH
        if ssh or sshtossh:
            self.port_entry.set_tooltip_text("Display number (optional)")
            self.port_entry.set_text("")
            self.ssh_port_entry.show()
            self.password_entry.set_tooltip_text("SSH Password")
            self.username_entry.set_tooltip_text("SSH Username")
            if ssh:
                self.proxy_vbox.hide()
                self.password_scb.hide()
                self.password_entry.set_sensitive(True)
                self.username_entry.set_sensitive(True)
            if sshtossh:
                self.proxy_vbox.show()
                self.password_scb.show()
        else:
            self.password_entry.set_sensitive(True)
            self.username_entry.set_sensitive(True)
            self.proxy_vbox.hide()
            self.ssh_port_entry.hide()
            self.ssh_port_entry.set_text("")
            port_str = self.port_entry.get_text()
            if not port_str:
                self.port_entry.set_text(str(max(0, self.config.port) or DEFAULT_PORT))
            self.port_entry.set_tooltip_text("xpra server port number")
            self.password_entry.set_tooltip_text("Session Password (optional)")
            self.username_entry.set_tooltip_text("Session Username (optional)")
            if self.config.port > 0:
                self.port_entry.set_text(str(self.config.port))
        can_use_password = True
        sshpass = False
        if ssh or sshtossh:
            if not self.is_putty:
                self.proxy_key_entry.set_text("OpenSSH/Paramiko use ~/.ssh")
                self.proxy_key_entry.set_editable(False)
                self.proxy_key_entry.set_sensitive(False)
                self.proxy_key_browse.hide()
            if self.is_paramiko or self.is_putty:
                can_use_password = True
            else:
                # we can also use password if sshpass is installed:
                from xpra.platform.paths import get_sshpass_command
                sshpass = get_sshpass_command()
                can_use_password = bool(sshpass)
                sshpass = bool(sshpass)
        if can_use_password:
            self.password_hbox.show()
            if sshtossh:
                self.proxy_password_hbox.show()
                # sshpass cannot do different username/passwords for proxy and destination
                if not sshpass:
                    self.check_boxes_hbox.show()
                    p = self.password_entry.get_text()
                    pp = self.proxy_password_entry.get_text()
                    u = self.username_entry.get_text()
                    pu = self.proxy_username_entry.get_text()
                else:
                    self.check_boxes_hbox.hide()
                    p = pp = None
                    u = pu = None
                self.password_scb.set_active(p == pp)
                self.username_scb.set_active(u == pu)
        else:
            self.password_hbox.hide()
            if sshtossh:
                self.check_boxes_hbox.hide()
                self.proxy_password_hbox.hide()
        can_use_path = mode in ("ws", "wss")
        if can_use_path:
            self.path_entry.show()
        else:
            self.path_entry.hide()
        self.validate()
        if mode in (MODE_SSL, MODE_WSS, MODE_QUIC) or (mode == MODE_SSH and not WIN32):
            self.nostrict_host_check.show()
        else:
            self.nostrict_host_check.hide()

    def reset_errors(self) -> None:
        self.set_sensitive(True)
        self.set_info_text("")
        for widget in (
                self.info, self.password_entry, self.username_entry, self.host_entry,
                self.port_entry, self.proxy_password_entry, self.proxy_username_entry,
                self.proxy_host_entry, self.proxy_port_entry, self.ssh_port_entry,
        ):
            set_widget_fg_color(self.info, False)
            set_widget_bg_color(widget, False)

    def set_info_text(self, text, is_error=False) -> None:
        if self.info:
            def do_set_info() -> None:
                self.info.set_text(text)
                self.info.set_selectable(is_error)
                set_widget_fg_color(self.info, is_error)

            GLib.idle_add(do_set_info)

    def set_sensitive(self, s) -> None:
        GLib.idle_add(self.window.set_sensitive, s)

    def choose_pkey_file(self, title, action, action_button, callback) -> None:
        file_filter = Gtk.FileFilter()
        file_filter.set_name("All Files")
        file_filter.add_pattern("*")
        choose_file(self.window, title, action, action_button, callback, file_filter)

    def proxy_key_browse_clicked(self, *args) -> None:
        log("proxy_key_browse_clicked%s", args)

        def do_choose(filename) -> None:
            # make sure the file extension is .ppk
            if os.path.splitext(filename)[-1] != ".ppk":
                filename += ".ppk"
            self.proxy_key_entry.set_text(filename)

        self.choose_pkey_file("Choose SSH private key", Gtk.FileChooserAction.OPEN, Gtk.STOCK_OPEN, do_choose)

    def connect_clicked(self, *args) -> None:
        log(f"connect_clicked({args})")
        self.update_options_from_gui()
        self.do_connect()

    def clean_client(self) -> None:
        c = self.client
        if c:
            c.disconnect_and_quit = noop
            c.warn_and_quit = noop
            c.quit = noop
            c.exit = noop
            c.cleanup()

    def handle_exception(self, e) -> None:
        log(f"handle_exception({e})")
        t = str(e)
        log("handle_exception: %s", traceback.format_exc())
        if self.config.debug:
            # in debug mode, include the full stacktrace:
            t = traceback.format_exc()

        def ui_handle_exception() -> None:
            self.clean_client()
            self.set_sensitive(True)
            if not self.current_error:
                self.current_error = t
                self.set_info_text(t, True)
            self.window.show()
            self.window.present()

        GLib.idle_add(ui_handle_exception)

    def do_connect(self) -> None:
        try:
            self.connect_builtin()
        except Exception as e:
            log.error("Error: cannot connect", exc_info=True)
            self.handle_exception(e)

    def connect_builtin(self) -> None:
        # cooked vars used by connect_to
        username = self.config.username
        params = {
            "type": self.config.mode,
            "username": username,
        }
        if self.config.mode in (MODE_SSH, MODE_NESTED_SSH):
            if self.config.socket_dir:
                params["socket_dir"] = self.config.socket_dir
            params["remote_xpra"] = self.config.remote_xpra
            params["proxy_command"] = ["_proxy"]
            if self.config.port >= 0:
                params["display"] = f":{self.config.port}"
                params["display_as_args"] = [params["display"]]
            else:
                params["display"] = "auto"
                params["display_as_args"] = []
            params["ssh"] = self.config.ssh
            params["is_putty"] = self.is_putty
            params["is_paramiko"] = self.is_paramiko
            password = self.config.password
            host = self.config.host
            upos = host.find("@")
            if upos >= 0:
                # found at sign: username@host
                username = host[:upos]
                host = host[upos + 1:]
                ppos = username.find(":")
                if ppos >= 0:
                    # found separator: username:password@host
                    password = username[ppos + 1:]
                    username = username[:ppos]
            if self.config.ssh_port and self.config.ssh_port != 22:
                params["port"] = self.config.ssh_port
            params["host"] = host
            ssh_cmd = parse_ssh_option(self.config.ssh)
            ssh_cmd_0 = ssh_cmd[0].strip().lower()
            self.is_putty = ssh_cmd_0.endswith("plink") or ssh_cmd_0.endswith("plink.exe")
            self.is_paramiko = ssh_cmd_0 == "paramiko"
            full_ssh = ssh_cmd[:]
            full_ssh += get_ssh_args(params, ssh_cmd)
            if username:
                params["username"] = username
            if self.nostrict_host_check.get_active():
                full_ssh += ["-o", "StrictHostKeyChecking=no"]
            if params["type"] == MODE_NESTED_SSH:
                params["type"] = "ssh"
                params["proxy_host"] = self.config.proxy_host
                params["proxy_port"] = self.config.proxy_port
                params["proxy_username"] = self.config.proxy_username
                params["proxy_password"] = self.config.proxy_password
                full_ssh += get_ssh_proxy_args(params, ssh_cmd)
            params["host"] = host
            params["local"] = is_local(self.config.host)
            params["full_ssh"] = full_ssh
            params["password"] = password
            params["display_name"] = f"ssh://{self.config.host}:{self.config.port}"
        elif self.config.mode == "display":
            params["display"] = f":{self.config.port}"
            params["display_name"] = f":{self.config.port}"
        elif self.config.mode in ("socket", "unix-domain"):
            params["display"] = f":{self.config.port}"
            params["display_name"] = f"unix-domain:{self.config.port}"
        else:
            if self.config.mode not in (MODE_TCP, MODE_SSL, MODE_QUIC, MODE_WS, MODE_WSS):
                raise ValueError(f"invalid / unsupported mode {self.config.mode}")
            params["host"] = self.config.host
            params["local"] = is_local(self.config.host)
            params["port"] = int(self.config.port)
            params["display_name"] = f"{self.config.mode}://{self.config.host}:{self.config.port}"
            if self.config.mode in (MODE_WS, MODE_WSS):
                params["path"] = self.config.path
            # always try to populate ssl so we can auto-upgrade:
            try:
                params["ssl-options"] = get_ssl_options(params, self.config, [])
            except ImportError:
                # perhaps ssl is missing or blocked
                pass
            if self.config.mode in (MODE_SSL, MODE_WSS, MODE_QUIC) and self.nostrict_host_check.get_active():
                params["strict-host-check"] = False

        # print("connect_to(%s)" % params)
        # UGLY warning: the username may have been updated during display parsing,
        # or the config file may contain a username which is different from the default one
        # which is used for initializing the client during init,
        # so update the client now:
        configure_env(self.config.env)
        configure_logging(self.config, "attach")
        configure_network(self.config)
        self.start_client(params)

    def start_client(self, display_desc: dict) -> None:
        bypass_no_gtk()
        self.client = make_client(self.config)
        self.client.show_progress(30, "client configuration")
        self.client.init(self.config)
        self.client.show_progress(40, "loading user interface")
        self.client.init_ui(self.config)
        self.client.username = display_desc.get("username")

        def handshake_complete(*_args) -> None:
            self.client.show_progress(100, "Session connected")

        self.client.after_handshake(handshake_complete)
        self.set_info_text("Connecting...")
        start_thread(self.do_connect_builtin, "connect", daemon=True, args=(display_desc,))

    def ssh_failed(self, message) -> None:
        log(f"ssh_failed({message})")
        if not self.current_error:
            self.current_error = message
            self.set_info_text(message, True)

    def do_connect_builtin(self, display_desc: dict) -> None:
        log(f"do_connect_builtin({display_desc})")
        self.exit_code = None
        self.current_error = None
        self.set_info_text("Connecting.")
        self.set_sensitive(False)
        self.client.show_progress(60, "connecting")
        try:
            log("calling %s%s", connect_to,
                (display_desc, repr_ellipsized(str(self.config)), self.set_info_text, self.ssh_failed))
            conn = connect_to(display_desc, opts=self.config,
                              debug_cb=self.set_info_text, ssh_fail_cb=self.ssh_failed)
        except Exception as e:
            log("do_connect_builtin(%s) failed to connect", display_desc, exc_info=True)
            self.handle_exception(e)
            return
        log("connect_to(..)=%s, hiding launcher window, starting client", conn)
        GLib.idle_add(self.start_xpra_client, conn, display_desc)

    def start_xpra_client(self, conn, display_desc: dict) -> None:
        try:
            self.do_start_xpra_client(conn, display_desc)
        except Exception as e:
            log.error("Error: failed to start client", exc_info=True)
            self.handle_exception(e)

    def do_start_xpra_client(self, conn, display_desc: dict) -> None:
        log("do_start_XpraClient(%s, %s) client=%s", conn, display_desc, self.client)
        self.client.encoding = self.config.encoding
        self.client.display_desc = display_desc
        self.client.make_protocol(conn)
        self.set_info_text("Network connection established")
        log("start_XpraClient() client initialized")

        if self.config.password:
            self.client.password = self.config.password

        def do_quit(*args) -> None:
            log("do_quit%s", args)
            self.clean_client()
            self.destroy()
            Gtk.main_quit()

        def handle_client_quit(exit_launcher=False) -> None:
            w = self.window
            log("handle_quit(%s) window=%s", exit_launcher, w)
            self.clean_client()
            if exit_launcher:
                # give time for the main loop to run once after calling cleanup
                GLib.timeout_add(100, do_quit)
            else:
                if w:
                    self.set_sensitive(True)
                    GLib.idle_add(w.show)

        def reconnect(exit_code) -> bool:
            log("reconnect(%s) config reconnect=%s",
                exit_str(exit_code), self.config.reconnect)
            if not self.config.reconnect or exit_code not in RETRY_EXIT_CODES:
                return False
            self.clean_client()
            # give time for the main loop to run once after calling cleanup
            GLib.timeout_add(100, self.start_client, display_desc)
            return True

        def warn_and_quit_override(exit_code, warning) -> None:
            log("warn_and_quit_override(%s, %s)", exit_code, warning)
            password_warning = warning.find("invalid password") >= 0
            if password_warning:
                self.password_warning()
            elif reconnect(exit_code):
                return
            if self.exit_code is None:
                self.exit_code = exit_code
            err = exit_code != 0 or password_warning
            if not self.current_error:
                self.current_error = warning
                self.set_info_text(warning, err)
            handle_client_quit(not err)

        def quit_override(exit_code) -> None:
            log("quit_override(%s)", exit_code)
            if reconnect(exit_code):
                return
            if self.exit_code is None:
                self.exit_code = exit_code
                estr = exit_str(exit_code)
                self.set_info_text(estr, exit_code != ExitCode.OK)
            handle_client_quit(self.exit_code == 0)

        self.client.warn_and_quit = warn_and_quit_override
        self.client.quit = quit_override

        def after_handshake() -> None:
            self.set_info_text("Handshake complete")

        self.client.after_handshake(after_handshake)

        def first_ui_received(*_args) -> None:
            self.set_info_text("Running")
            self.window.hide()

        self.client.connect("first-ui-received", first_ui_received)
        if Gtk.main_level() > 0:
            # no need to start a new main loop:
            self.client.gtk_main = noop
        try:
            r = self.client.run()
            log("client.run() returned %s", r)
        except Exception as e:
            log.error("client error", exc_info=True)
            self.handle_exception(e)
        if self.client.gtk_main == noop:
            return
        log("exit_launcher=%s", self.exit_launcher)
        # if we're using "autoconnect",
        # the main loop was running from here,
        # so we have to force exit if the launcher window had been closed:
        if self.exit_launcher:
            sys.exit(0)

    def password_ok(self, *_args) -> None:
        with IgnoreWarningsContext():
            self.password_entry.modify_text(Gtk.StateType.NORMAL, black)

    def password_warning(self, *_args) -> None:
        with IgnoreWarningsContext():
            self.password_entry.modify_text(Gtk.StateType.NORMAL, red)
        self.password_entry.grab_focus()

    def update_options_from_gui(self) -> None:
        def pint(vstr, default=0) -> int:
            try:
                return int(vstr)
            except ValueError:
                return default

        self.config.host = self.host_entry.get_text()
        self.config.ssh_port = pint(self.ssh_port_entry.get_text())
        self.config.port = pint(self.port_entry.get_text(), -1)
        self.config.username = self.username_entry.get_text()
        self.config.password = self.password_entry.get_text()
        self.config.path = self.path_entry.get_text()
        self.config.autoconnect = self.autoconnect.get_active()

        self.config.proxy_host = self.proxy_host_entry.get_text()
        self.config.proxy_port = pint(self.proxy_port_entry.get_text())
        self.config.proxy_username = self.proxy_username_entry.get_text()
        self.config.proxy_password = self.proxy_password_entry.get_text()
        if self.is_putty:
            self.config.proxy_key = self.proxy_key_entry.get_text()

        mode_enc = self.mode_combo.get_active_text().lower()
        if mode_enc.startswith(MODE_TCP):
            self.config.mode = MODE_TCP
            if mode_enc.find("aes") > 0:
                self.config.encryption = "AES-" + mode_enc.split("aes-")[1].upper()
        elif mode_enc in (MODE_SSL, MODE_QUIC, MODE_SSH, MODE_WS, MODE_WSS, MODE_NESTED_SSH):
            self.config.mode = mode_enc
            self.config.encryption = ""
        log("update_options_from_gui() %s",
            (self.config.username, self.config.password, self.config.mode, self.config.encryption,
             self.config.host, self.config.port, self.config.ssh_port))

    def update_gui_from_config(self) -> None:
        mode = (self.config.mode or "").lower()
        active = 0
        for i, e in enumerate(get_connection_modes()):
            if e.lower() == mode:
                active = i
                break
        self.mode_combo.set_active(active)

        def get_port(vstr, default_port="") -> str:
            try:
                iport = int(vstr)
                if 0 <= iport < 2 ** 16:
                    return str(iport)
            except ValueError:
                pass
            return str(default_port)

        dport = DEFAULT_PORT
        if mode in (MODE_SSH, MODE_NESTED_SSH):
            # not required, so don't specify one
            dport = ""
        self.port_entry.set_text(get_port(self.config.port, dport))
        self.ssh_port_entry.set_text(get_port(self.config.ssh_port))
        # proxy bits:
        self.proxy_host_entry.set_text(self.config.proxy_host)
        self.proxy_port_entry.set_text(get_port(self.config.proxy_port))
        username = self.config.username
        proxy_username = self.config.proxy_username
        self.username_scb.set_active(username == proxy_username)
        self.proxy_username_entry.set_text(proxy_username)
        password = self.config.password
        proxy_password = self.config.proxy_password
        self.password_scb.set_active(password == proxy_password)
        self.proxy_password_entry.set_text(proxy_password)
        if self.is_putty:
            self.proxy_key_entry.set_text(self.config.proxy_key)
        self.username_entry.set_text(username)
        self.password_entry.set_text(password)
        self.host_entry.set_text(self.config.host)
        self.path_entry.set_text(self.config.path)

    def close_window(self, *_args) -> None:
        w = self.window
        if w:
            self.window = None
            w.destroy()

    def destroy(self, *args) -> bool:
        log("destroy%s", args)
        self.exit_launcher = True
        self.clean_client()
        self.close_window()
        Gtk.main_quit()
        return False

    def update_options_from_url(self, url: str) -> None:
        from xpra.scripts.parsing import parse_URL
        address, props = parse_URL(url)
        pa = address.split("://")
        if pa[0] in (MODE_TCP, MODE_SSH, MODE_SSL, MODE_QUIC, MODE_WS, MODE_WSS) and len(pa) >= 2:
            props["mode"] = pa[0]
            host = pa[1]
            if host.find("@") > 0:
                username, host = host.rsplit("@", 1)
                if username.find(":") > 0:
                    username, password = username.rsplit(":", 1)
                    props["password"] = password
                props["username"] = username
            if host.find(":") > 0:
                host, port = host.rsplit(":", 1)
                props["port"] = int(port)
            props["host"] = host
        self._apply_props(props)

    def update_options_from_file(self, filename: str) -> None:
        props = read_config(filename)
        log("update_options_from_file(%s) props=%s", filename, props)
        self._apply_props(props)

    def _apply_props(self, props: dict[str, Any]) -> None:
        # we rely on "ssh_port" being defined on the config object
        # so try to load it from file, and define it if not present:
        options = validate_config(props,
                                  extras_types=LAUNCHER_OPTION_TYPES,
                                  extras_validation=get_launcher_validation())
        for k, v in options.items():
            fn = k.replace("-", "_")
            setattr(self.config, fn, v)
        self.config_keys = self.config_keys.union(set(props.keys()))
        self.parse_ssh()
        log("_apply_props(%s) populated config with keys '%s', ssh=%s", props, options.keys(), self.config.ssh)

    def choose_session_file(self, title: str, action, action_button, callback: Callable):
        file_filter = Gtk.FileFilter()
        file_filter.set_name("Xpra")
        file_filter.add_pattern("*.xpra")
        choose_file(self.window, title, action, action_button, callback, file_filter)

    def save_clicked(self, *_args) -> None:
        self.update_options_from_gui()

        def do_save(filename) -> None:
            # make sure the file extension is .xpra
            if os.path.splitext(filename)[-1] != ".xpra":
                filename += ".xpra"
            save_config(filename, self.config, self.config_keys, extras_types=LAUNCHER_OPTION_TYPES)

        self.choose_session_file("Save session settings to file", Gtk.FileChooserAction.SAVE, Gtk.STOCK_SAVE, do_save)

    def load_clicked(self, *_args) -> None:
        def do_load(filename) -> None:
            self.update_options_from_file(filename)
            self.update_gui_from_config()

        self.choose_session_file("Load session settings from file", Gtk.FileChooserAction.OPEN, Gtk.STOCK_OPEN, do_load)


# on some platforms like win32, we don't have stdout
# and this is a GUI application, so show a dialog with the error instead
def exception_dialog(title: str) -> None:
    md = Gtk.MessageDialog(None, Gtk.DialogFlags.DESTROY_WITH_PARENT,
                           Gtk.MessageType.INFO, Gtk.ButtonsType.CLOSE, title)
    md.format_secondary_text(traceback.format_exc())
    md.show_all()

    def close_dialog(*_args) -> None:
        md.destroy()
        Gtk.main_quit()

    md.connect("response", close_dialog)
    md.connect("close", close_dialog)
    Gtk.main()


def main(argv) -> int:
    from xpra.platform import program_context
    from xpra.log import enable_color
    with program_context("Xpra-Launcher", "Xpra Connection Launcher"):
        enable_color()
        return do_main(argv)


def do_main(argv: list[str]) -> int:
    from xpra.util.system import SIGNAMES
    from xpra.scripts.main import InitExit, InitInfo
    from xpra.platform.gui import init as gui_init, ready as gui_ready
    from xpra.gtk.util import init_display_source

    init_display_source()

    gui_init()
    try:
        from xpra.scripts.parsing import parse_cmdline, fixup_debug_option
        options, args = parse_cmdline(argv)
        debug = fixup_debug_option(options.debug)
        if debug:
            enable_debug_for(*debug.split(","))
    except InitInfo as e:
        print(str(e))
        return 0
    except InitExit as e:
        return e.status
    except Exception:
        exception_dialog("Error parsing command line")
        return 1

    # allow config to be debugged:
    from xpra.scripts import config
    config.debug = log.debug

    try:
        app = ApplicationWindow()

        def handle_signal(signum) -> None:
            app.show()
            client = app.client
            if client:
                client.cleanup()
            else:
                Gtk.main_quit()
            GLib.timeout_add(1000, app.set_info_text, "got signal " + SIGNAMES.get(signum, signum))

        register_os_signals(handle_signal, "Client Launcher")
        has_file = len(args) == 1
        if has_file:
            app.update_options_from_file(args[0])
            # the compressors and packet encoders cannot be changed from the UI
            # so apply them now:
            configure_env(app.config.env)
            configure_network(app.config)
        debug = fixup_debug_option(app.config.debug)
        if debug:
            enable_debug_for(*debug.split(","))
        app.create_window_with_config()
    except Exception:
        exception_dialog("Error creating launcher form")
        return 1
    try:
        if app.config.autoconnect:
            # file says we should connect,
            # do that only (not showing UI unless something goes wrong):
            GLib.idle_add(app.do_connect)
        if not has_file:
            app.reset_errors()
        if not app.config.autoconnect or app.config.debug:
            if OSX:
                from xpra.platform.darwin.gui import wait_for_open_handlers, force_focus
                if has_file:
                    force_focus()
                    app.show()
                else:
                    def open_file(filename: str) -> None:
                        log("open_file(%s)", filename)
                        app.update_options_from_file(filename)
                        # the compressors and packet encoders cannot be changed from the UI
                        # so apply them now:
                        configure_network(app.config)
                        app.update_gui_from_config()
                        if app.config.autoconnect:
                            app.__osx_open_signal = True
                            GLib.idle_add(app.do_connect)
                        else:
                            force_focus()
                            app.show()

                    def open_URL(url: str) -> None:
                        log("open_URL(%s)", url)
                        app.__osx_open_signal = True
                        app.update_options_from_url(url)
                        # the compressors and packet encoders cannot be changed from the UI
                        # so apply them now:
                        configure_network(app.config)
                        app.update_gui_from_config()
                        GLib.idle_add(app.do_connect)

                    wait_for_open_handlers(app.show, open_file, open_URL)
            else:
                app.show()
        gui_ready()
        app.run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
