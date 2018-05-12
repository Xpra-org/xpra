#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2009-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

""" client_launcher.py

This is a simple GUI for starting the xpra client.

"""

import os.path
import sys
import shlex
import signal
import traceback

from xpra.gtk_common.gobject_compat import import_gtk, import_gdk, import_gobject, import_pango, import_glib
gobject = import_gobject()
gobject.threads_init()
glib = import_glib()
glib.threads_init()
gtk = import_gtk()
gdk = import_gdk()
pango = import_pango()

from xpra.platform.gui import init as gui_init
gui_init()

from xpra.scripts.config import read_config, make_defaults_struct, validate_config, save_config
from xpra.codecs.loader import PREFERED_ENCODING_ORDER
from xpra.gtk_common.gtk_util import gtk_main, add_close_accel, scaled_image, pixbuf_new_from_file, color_parse, \
                                    OptionMenu, choose_file, set_use_tray_workaround, window_defaults, imagebutton, \
                                    WIN_POS_CENTER, STATE_NORMAL, \
                                    DESTROY_WITH_PARENT, MESSAGE_INFO,  BUTTONS_CLOSE, \
                                    FILE_CHOOSER_ACTION_SAVE, FILE_CHOOSER_ACTION_OPEN
from xpra.util import DEFAULT_PORT, csv
from xpra.os_util import thread, WIN32, OSX, PYTHON3
from xpra.client.gtk_base.gtk_tray_menu_base import make_min_auto_menu, make_encodingsmenu, \
                                    MIN_QUALITY_OPTIONS, QUALITY_OPTIONS, MIN_SPEED_OPTIONS, SPEED_OPTIONS
from xpra.gtk_common.about import about
from xpra.scripts.main import connect_to, make_client, configure_network, is_local
from xpra.platform.paths import get_icon_dir
from xpra.platform import get_username
from xpra.log import Logger, enable_debug_for
log = Logger("launcher")

#what we save in the config file:
SAVED_FIELDS = ["username", "password", "host", "port", "mode", "ssh_port",
                "encoding", "quality", "min-quality", "speed", "min-speed"]

#options not normally found in xpra config file
#but which can be present in a launcher config:
LAUNCHER_OPTION_TYPES ={
                        "host"              : str,
                        "port"              : int,
                        "username"          : str,
                        "password"          : str,
                        "mode"              : str,
                        "autoconnect"       : bool,
                        "ssh_port"          : int,
                        }
LAUNCHER_DEFAULTS = {
                        "host"              : "",
                        "port"              : -1,
                        "username"          : get_username(),
                        "password"          : "",
                        "mode"              : "tcp",    #tcp,ssh,..
                        "autoconnect"       : False,
                        "ssh_port"          : 22,
                    }


black   = color_parse("black")
red     = color_parse("red")
white   = color_parse("white")


def get_active_item_index(optionmenu):
    menu = optionmenu.get_menu()
    for i, x in enumerate(menu.get_children()):
        if hasattr(x, "get_active") and x.get_active():
            return i
    return -1

def set_history_from_active(optionmenu):
    #Used for OptionMenu combo:
    #sets the first active menu entry as the "history" value (the selected item)
    i = get_active_item_index(optionmenu)
    if i>0:
        optionmenu.set_history(i)


def has_mdns():
    try:
        from xpra.net.mdns import get_listener_class
        lc = get_listener_class()
        log("mdns listener class: %s", lc)
        if lc:
            return True
    except ImportError as e:
        log("no mdns support: %s", e)
    return False


class ApplicationWindow:

    def    __init__(self):
        # Default connection options
        self.config = make_defaults_struct(extras_defaults=LAUNCHER_DEFAULTS, extras_types=LAUNCHER_OPTION_TYPES, extras_validation=self.get_launcher_validation())
        #TODO: the fixup does not belong here?
        from xpra.scripts.main import fixup_options
        fixup_options(self.config)
        #what we save by default:
        self.config_keys = set(SAVED_FIELDS)
        def raise_exception(*args):
            raise Exception(*args)
        self.client = make_client(raise_exception, self.config)
        self.client.init(self.config)
        self.exit_code = None
        self.current_error = None

    def get_connection_modes(self):
        modes = ["ssh"]
        try:
            import ssl
            assert ssl
            modes.append("ssl")
        except:
            pass
        #assume crypto is available
        modes.append("tcp + aes")
        modes.append("tcp")
        return modes

    def get_launcher_validation(self):
        #TODO: since "mode" is not part of global options
        #this validation should be injected from the launcher instead
        def validate_in_list(x, options):
            if x in options:
                return None
            return "must be in %s" % csv(options)
        modes = self.get_connection_modes()
        return {"mode"              : lambda x : validate_in_list(x, modes)}


    def image_button(self, label="", tooltip="", icon_pixbuf=None, clicked_cb=None):
        icon = gtk.Image()
        icon.set_from_pixbuf(icon_pixbuf)
        return imagebutton(label, icon, tooltip, clicked_cb, icon_size=None)

    def create_window(self):
        self.window = gtk.Window()
        window_defaults(self.window)
        self.window.connect("destroy", self.destroy)
        self.window.set_default_size(400, 260)
        self.window.set_title("Xpra Launcher")

        self.window.set_position(WIN_POS_CENTER)

        vbox = gtk.VBox(False, 0)
        vbox.set_spacing(15)

        #top row:
        hbox = gtk.HBox(False, 0)
        # About dialog (and window icon):
        icon_pixbuf = self.get_icon("xpra.png")
        if icon_pixbuf:
            self.window.set_icon(icon_pixbuf)
            logo_button = self.image_button("", "About", icon_pixbuf, about)
            hbox.pack_start(logo_button, expand=False, fill=False)
        # Bug report tool link:
        icon_pixbuf = self.get_icon("bugs.png")
        self.bug_tool = None
        if icon_pixbuf:
            def bug(*_args):
                if self.bug_tool==None:
                    from xpra.client.gtk_base.bug_report import BugReport
                    self.bug_tool = BugReport()
                    self.bug_tool.init(show_about=False)
                self.bug_tool.show()
            bug_button = self.image_button("", "Bug Report", icon_pixbuf, bug)
            hbox.pack_start(bug_button, expand=False, fill=False)
        # Session browser link:
        icon_pixbuf = self.get_icon("mdns.png")
        self.mdns_gui = None
        if icon_pixbuf and has_mdns():
            def mdns(*_args):
                if self.mdns_gui==None:
                    from xpra.client.gtk_base.mdns_gui import mdns_sessions
                    self.mdns_gui = mdns_sessions(self.config)
                    def close_mdns():
                        self.mdns_gui.destroy()
                        self.mdns_gui = None
                    self.mdns_gui.do_quit = close_mdns
                else:
                    self.mdns_gui.present()
            mdns_button = self.image_button("", "Browse Sessions", icon_pixbuf, mdns)
            hbox.pack_start(mdns_button, expand=False, fill=False)

        # Title
        label = gtk.Label("Connect to xpra server")
        label.modify_font(pango.FontDescription("sans 14"))
        hbox.pack_start(label, expand=True, fill=True)
        vbox.pack_start(hbox)

        # Mode:
        hbox = gtk.HBox(False, 20)
        hbox.set_spacing(20)
        hbox.pack_start(gtk.Label("Mode: "))
        self.mode_combo = gtk.combo_box_new_text()
        for x in self.get_connection_modes():
            self.mode_combo.append_text(x.upper())
        self.mode_combo.connect("changed", self.mode_changed)
        hbox.pack_start(self.mode_combo)
        vbox.pack_start(hbox)

        # Username@Host:Port
        hbox = gtk.HBox(False, 0)
        hbox.set_spacing(5)
        self.username_entry = gtk.Entry()
        self.username_entry.set_max_length(128)
        self.username_entry.set_width_chars(16)
        self.username_entry.connect("changed", self.validate)
        self.username_entry.set_tooltip_text("username")
        self.username_label = gtk.Label("@")
        self.host_entry = gtk.Entry()
        self.host_entry.set_max_length(128)
        self.host_entry.set_width_chars(24)
        self.host_entry.connect("changed", self.validate)
        self.host_entry.set_tooltip_text("hostname")
        self.ssh_port_entry = gtk.Entry()
        self.ssh_port_entry.set_max_length(5)
        self.ssh_port_entry.set_width_chars(5)
        self.ssh_port_entry.connect("changed", self.validate)
        self.ssh_port_entry.set_tooltip_text("SSH port")
        self.port_entry = gtk.Entry()
        self.port_entry.set_max_length(5)
        self.port_entry.set_width_chars(5)
        self.port_entry.connect("changed", self.validate)
        self.port_entry.set_tooltip_text("port/display")

        hbox.pack_start(self.username_entry)
        hbox.pack_start(self.username_label)
        hbox.pack_start(self.host_entry)
        hbox.pack_start(self.ssh_port_entry)
        hbox.pack_start(gtk.Label(":"))
        hbox.pack_start(self.port_entry)
        vbox.pack_start(hbox)

        # Password
        hbox = gtk.HBox(False, 0)
        hbox.set_spacing(20)
        self.password_entry = gtk.Entry()
        self.password_entry.set_max_length(128)
        self.password_entry.set_width_chars(30)
        self.password_entry.set_text("")
        self.password_entry.set_visibility(False)
        self.password_entry.connect("changed", self.password_ok)
        self.password_entry.connect("changed", self.validate)
        self.password_label = gtk.Label("Password: ")
        hbox.pack_start(self.password_label)
        hbox.pack_start(self.password_entry)
        vbox.pack_start(hbox)

        #strict host key check for SSL and SSH
        hbox = gtk.HBox(False, 0)
        hbox.set_spacing(20)
        self.nostrict_host_check = gtk.CheckButton("Disable Strict Host Key Check")
        self.nostrict_host_check.set_active(False)
        al = gtk.Alignment(xalign=0.5, yalign=0.5, xscale=0.0, yscale=0)
        al.add(self.nostrict_host_check)
        hbox.pack_start(al)
        vbox.pack_start(hbox)

        # Info Label
        self.info = gtk.Label()
        self.info.set_line_wrap(True)
        self.info.set_size_request(360, -1)
        self.info.modify_fg(STATE_NORMAL, red)
        vbox.pack_start(self.info)

        #hide encoding options by default
        self.encoding_combo = None
        self.encoding_options_check = None
        self.encoding_box = None
        if not PYTHON3:
            #not implemented for gtk3, where we can't use set_menu()...
            hbox = gtk.HBox(False, 0)
            hbox.set_spacing(20)
            self.encoding_options_check = gtk.CheckButton("Advanced Encoding Options")
            self.encoding_options_check.connect("toggled", self.encoding_options_toggled)
            self.encoding_options_check.set_active(False)
            al = gtk.Alignment(xalign=0.5, yalign=0.5, xscale=0.0, yscale=0)
            al.add(self.encoding_options_check)
            hbox.pack_start(al)
            vbox.pack_start(hbox)
            self.encoding_box = gtk.VBox()
            vbox.pack_start(self.encoding_box)

            # Encoding:
            hbox = gtk.HBox(False, 20)
            hbox.set_spacing(20)
            hbox.pack_start(gtk.Label("Encoding: "))
            self.encoding_combo = OptionMenu()
            def get_current_encoding():
                return self.config.encoding
            def set_new_encoding(e):
                self.config.encoding = e
            encodings = ["auto"]+[x for x in PREFERED_ENCODING_ORDER if x in self.client.get_encodings()]
            server_encodings = encodings
            es = make_encodingsmenu(get_current_encoding, set_new_encoding, encodings, server_encodings)
            self.encoding_combo.set_menu(es)
            set_history_from_active(self.encoding_combo)
            hbox.pack_start(self.encoding_combo)
            self.encoding_box.pack_start(hbox)
            self.encoding_combo.connect("changed", self.encoding_changed)

            # Quality
            hbox = gtk.HBox(False, 20)
            hbox.set_spacing(20)
            self.quality_label = gtk.Label("Quality: ")
            hbox.pack_start(self.quality_label)
            self.quality_combo = OptionMenu()
            def set_min_quality(q):
                self.config.min_quality = q
            def set_quality(q):
                self.config.quality = q
            def get_min_quality():
                return self.config.min_quality
            def get_quality():
                return self.config.quality
            sq = make_min_auto_menu("Quality", MIN_QUALITY_OPTIONS, QUALITY_OPTIONS,
                                       get_min_quality, get_quality, set_min_quality, set_quality)
            self.quality_combo.set_menu(sq)
            set_history_from_active(self.quality_combo)
            hbox.pack_start(self.quality_combo)
            self.encoding_box.pack_start(hbox)

            # Speed
            hbox = gtk.HBox(False, 20)
            hbox.set_spacing(20)
            self.speed_label = gtk.Label("Speed: ")
            hbox.pack_start(self.speed_label)
            self.speed_combo = OptionMenu()
            def set_min_speed(s):
                self.config.min_speed = s
            def set_speed(s):
                self.config.speed = s
            def get_min_speed():
                return self.config.min_speed
            def get_speed():
                return self.config.speed
            ss = make_min_auto_menu("Speed", MIN_SPEED_OPTIONS, SPEED_OPTIONS,
                                       get_min_speed, get_speed, set_min_speed, set_speed)
            self.speed_combo.set_menu(ss)
            set_history_from_active(self.speed_combo)
            hbox.pack_start(self.speed_combo)
            self.encoding_box.pack_start(hbox)
            self.encoding_box.hide()

        # Buttons:
        hbox = gtk.HBox(False, 20)
        vbox.pack_start(hbox)
        #Save:
        self.save_btn = gtk.Button("Save")
        self.save_btn.set_tooltip_text("Save settings to a session file")
        self.save_btn.connect("clicked", self.save_clicked)
        hbox.pack_start(self.save_btn)
        #Load:
        self.load_btn = gtk.Button("Load")
        self.load_btn.set_tooltip_text("Load settings from a session file")
        self.load_btn.connect("clicked", self.load_clicked)
        hbox.pack_start(self.load_btn)
        # Connect button:
        self.button = gtk.Button("Connect")
        self.button.connect("clicked", self.connect_clicked)
        connect_icon = self.get_icon("retry.png")
        if connect_icon:
            self.button.set_image(scaled_image(connect_icon, 24))
        hbox.pack_start(self.button)

        add_close_accel(self.window, self.accel_close)
        vbox.show_all()
        self.encoding_options_toggled()
        self.window.vbox = vbox
        self.window.add(vbox)

    def accel_close(self, *args):
        log("accel_close%s", args)
        gtk.main_quit()

    def validate(self, *args):
        ssh = self.mode_combo.get_active_text()=="SSH"
        errs = []
        host = self.host_entry.get_text()
        errs.append((self.host_entry, not bool(host), "specify the host"))
        if ssh:
            #validate ssh port:
            ssh_port = self.ssh_port_entry.get_text()
            try:
                ssh_port = int(ssh_port)
            except:
                ssh_port = -1
            errs.append((self.ssh_port_entry, ssh_port<0 or ssh_port>=2**16, "invalid SSH port number"))
        port = self.port_entry.get_text()
        if ssh and not port:
            port = 0        #port optional with ssh
        else:
            try:
                port = int(port)
            except:
                port = -1
        errs.append((self.port_entry, port<0 or port>=2**16, "invalid port number"))
        err_text = []
        for w, e, text in errs:
            self.set_widget_bg_color(w, e)
            if e:
                err_text.append(text)
        log("validate(%s) err_text=%s, errs=%s", args, err_text, errs)
        self.set_info_text(csv(err_text))
        self.set_info_color(len(err_text)>0)
        self.button.set_sensitive(len(err_text)==0)
        return errs

    def show(self):
        self.window.show()
        self.window.present()

    def run(self):
        gtk_main()

    def get_icon(self, icon_name):
        icon_filename = os.path.join(get_icon_dir(), icon_name)
        if os.path.exists(icon_filename):
            return pixbuf_new_from_file(icon_filename)
        return None

    def mode_changed(self, *_args):
        mode = self.mode_combo.get_active_text().lower()
        ssh = mode=="ssh"
        if ssh:
            self.port_entry.set_tooltip_text("Display number (optional)")
            self.port_entry.set_text("")
            self.ssh_port_entry.set_text("22")
            self.ssh_port_entry.show()
            self.password_entry.set_tooltip_text("SSH Password")
            self.username_entry.set_tooltip_text("SSH Username")
        else:
            self.ssh_port_entry.hide()
            self.ssh_port_entry.set_text("")
            port_str = self.port_entry.get_text()
            if not port_str:
                self.port_entry.set_text(str(max(0, self.config.port) or DEFAULT_PORT))
            self.port_entry.set_tooltip_text("xpra server port number")
            self.password_entry.set_tooltip_text("Session Password (optional)")
            self.username_entry.set_tooltip_text("Session Username (optional)")
            if self.config.port>0:
                self.port_entry.set_text("%s" % self.config.port)
        can_use_password = not ssh
        if ssh:
            if WIN32:
                #plink can use password
                pass
            else:
                #can use password if sshpass is installed:
                from xpra.platform.paths import get_sshpass_command
                sshpass = get_sshpass_command()
                can_use_password = bool(sshpass)
        if can_use_password:
            self.password_label.show()
            self.password_entry.show()
        else:
            self.password_label.hide()
            self.password_entry.hide()
        self.validate()
        if mode=="ssl" or (mode=="ssh" and not WIN32):
            self.nostrict_host_check.show()
        else:
            self.nostrict_host_check.hide()

    def get_selected_encoding(self, *_args):
        if not self.encoding_combo:
            return ""
        index = get_active_item_index(self.encoding_combo)
        return self.encoding_combo.get_menu().index_to_encoding.get(index)

    def encoding_changed(self, *args):
        encoding = self.get_selected_encoding()
        uses_quality_option = encoding in ["jpeg", "webp", "h264", "auto"]
        log("encoding_changed(%s) uses_quality_option(%s)=%s", args, encoding, uses_quality_option)
        if uses_quality_option:
            self.quality_combo.show()
            self.quality_label.show()
        else:
            self.quality_combo.hide()
            self.quality_label.hide()

    def encoding_options_toggled(self, *_args):
        if not self.encoding_box:
            return
        show_opts = self.encoding_options_check.get_active()
        if show_opts:
            self.encoding_box.show()
        else:
            self.encoding_box.hide()

    def reset_errors(self):
        self.set_sensitive(True)
        self.set_info_text("")
        for widget in (self.info, self.password_entry, self.username_entry, self.host_entry, self.port_entry):
            self.set_widget_fg_color(self.info, False)
            self.set_widget_bg_color(widget, False)

    def set_info_text(self, text):
        if self.info:
            glib.idle_add(self.info.set_text, text)

    def set_info_color(self, is_error=False):
        self.set_widget_fg_color(self.info, is_error)


    def set_sensitive(self, s):
        glib.idle_add(self.window.set_sensitive, s)

    def connect_clicked(self, *_args):
        self.update_options_from_gui()
        self.do_connect()


    def reset_client(self):
        #lose current client class and make a new one:
        if self.client:
            self.client.cleanup()
            self.client = None
        self.client = make_client(Exception, self.config)
        self.client.init(self.config)


    def handle_exception(self, e):
        log("handle_exception(%s)", e)
        t = str(e)
        if self.config.debug:
            #in debug mode, include the full stacktrace:
            t = traceback.format_exc()
        def ui_handle_exception():
            self.reset_client()
            self.set_sensitive(True)
            if not self.current_error:
                self.current_error = t
                self.set_info_color(True)
                self.set_info_text(t)
            self.window.show()
            self.window.present()
        glib.idle_add(ui_handle_exception)

    def do_connect(self):
        try:
            self.connect_builtin()
        except Exception as e:
            log.error("cannot connect:", exc_info=True)
            self.handle_exception(e)

    def connect_builtin(self):
        #cooked vars used by connect_to
        params = {"type"    : self.config.mode}
        username = self.config.username
        if self.config.mode=="ssh":
            if self.config.socket_dir:
                params["socket_dir"] = self.config.socket_dir
            params["remote_xpra"] = self.config.remote_xpra
            params["proxy_command"] = ["_proxy"]
            if self.config.port and self.config.port>0:
                params["display"] = ":%s" % self.config.port
                params["display_as_args"] = [params["display"]]
            else:
                params["display"] = "auto"
                params["display_as_args"] = []
            full_ssh = shlex.split(self.config.ssh)
            password = self.config.password
            host = self.config.host
            upos = host.find("@")
            if upos>=0:
                #found at sign: username@host
                username = host[:upos]
                host = host[upos+1:]
                ppos = username.find(":")
                if ppos>=0:
                    #found separator: username:password@host
                    password = username[ppos+1:]
                    username = username[:ppos]
            if username:
                params["username"] = username
                full_ssh += ["-l", username]
            full_ssh += ["-T", host]
            if self.nostrict_host_check.get_active():
                full_ssh += ["-o", "StrictHostKeyChecking=no"]
            if str(self.config.ssh_port)!="22":
                if WIN32:
                    full_ssh += ["-P", str(self.config.ssh_port)]
                else:
                    full_ssh += ["-p", str(self.config.ssh_port)]
            params["host"] = host
            params["local"] = is_local(self.config.host)
            params["full_ssh"] = full_ssh
            params["password"] = password
            params["display_name"] = "ssh:%s:%s" % (self.config.host, self.config.port)
        elif self.config.mode=="unix-domain":
            params["display"] = ":%s" % self.config.port
            params["display_name"] = "unix-domain:%s" % self.config.port
        else:
            assert self.config.mode in ("tcp", "ssl"), "invalid / unsupported mode %s" % self.config.mode
            params["host"] = self.config.host
            params["local"] = is_local(self.config.host)
            params["port"] = int(self.config.port)
            params["display_name"] = "%s:%s:%s" % (self.config.mode, self.config.host, self.config.port)
            if self.config.mode=="ssl" and self.nostrict_host_check.get_active():
                params["strict-host-check"] = False

        #print("connect_to(%s)" % params)
        #UGLY warning: the username may have been updated during display parsing,
        #or the config file may contain a username which is different from the default one
        #which is used for initializing the client during init,
        #so update the client now:
        self.client.username = username
        self.set_info_text("Connecting...")
        thread.start_new_thread(self.do_connect_builtin, (params,))

    def ssh_failed(self, message):
        log("ssh_failed(%s)", message)
        if not self.current_error:
            self.current_error = message
            self.set_info_text(message)
            self.set_info_color(True)

    def do_connect_builtin(self, display_desc):
        log("do_connect_builtin(%s)", display_desc)
        self.exit_code = None
        self.current_error = None
        self.set_info_text("Connecting.")
        self.set_sensitive(False)
        try:
            conn = connect_to(display_desc, opts=self.config, debug_cb=self.set_info_text, ssh_fail_cb=self.ssh_failed)
        except Exception as e:
            log.error("failed to connect", exc_info=True)
            self.handle_exception(e)
            return
        glib.idle_add(self.window.hide)
        glib.idle_add(self.start_XpraClient, conn, display_desc)

    def start_XpraClient(self, conn, display_desc):
        try:
            self.do_start_XpraClient(conn, display_desc)
        except Exception as e:
            log.error("failed to start client", exc_info=True)
            self.handle_exception(e)

    def do_start_XpraClient(self, conn, display_desc={}):
        log("do_start_XpraClient(%s, %s) client=%s", conn, display_desc, self.client)
        self.client.encoding = self.config.encoding
        self.client.display_desc = display_desc
        #we have already initialized it,
        #but calling client.init will do it again - so we have to clear it:
        from xpra.codecs.video_helper import getVideoHelper
        getVideoHelper().cleanup()
        self.client.init(self.config)
        self.client.init_ui(self.config)
        self.client.setup_connection(conn)
        log("start_XpraClient() client initialized")

        if self.config.password:
            self.client.password = self.config.password
        #override exit code:
        warn_and_quit_save = self.client.warn_and_quit
        quit_save = self.client.quit
        def do_quit(*_args):
            self.client.warn_and_quit = warn_and_quit_save
            self.client.quit = quit_save
            self.client.cleanup()
            self.destroy()
            gtk.main_quit()
        def warn_and_quit_override(exit_code, warning):
            log("warn_and_quit_override(%s, %s)", exit_code, warning)
            if self.exit_code == None:
                self.exit_code = exit_code
            password_warning = warning.find("invalid password")>=0
            if password_warning:
                self.password_warning()
            err = exit_code!=0 or password_warning
            if not self.current_error:
                self.current_error = warning
                self.set_info_color(err)
                self.set_info_text(warning)
            if err:
                def ignore_further_quit_events(*args):
                    pass
                if self.client:
                    self.client.cleanup()
                    self.client.warn_and_quit = ignore_further_quit_events
                    self.client.quit = ignore_further_quit_events
                w = self.window
                if w:
                    self.set_sensitive(True)
                    self.reset_client()
                    glib.idle_add(w.show)
            else:
                do_quit()

        def quit_override(exit_code):
            log("quit_override(%s)", exit_code)
            if self.exit_code == None:
                self.exit_code = exit_code
            self.client.cleanup()
            if self.exit_code==0:
                do_quit()
            else:
                self.reset_client()

        self.client.warn_and_quit = warn_and_quit_override
        self.client.quit = quit_override
        try:
            self.client.run()
        except Exception as e:
            log.error("client error", exc_info=True)
            self.handle_exception(e)


    def password_ok(self, *_args):
        self.password_entry.modify_text(STATE_NORMAL, black)

    def password_warning(self, *_args):
        self.password_entry.modify_text(STATE_NORMAL, red)
        self.password_entry.grab_focus()

    def set_widget_bg_color(self, widget, is_error=False):
        if is_error:
            color_obj = red
        else:
            color_obj = white
        if color_obj:
            glib.idle_add(widget.modify_base, STATE_NORMAL, color_obj)

    def set_widget_fg_color(self, widget, is_error=False):
        if is_error:
            color_obj = red
        else:
            color_obj = black
        if color_obj:
            glib.idle_add(widget.modify_fg, STATE_NORMAL, color_obj)


    def update_options_from_gui(self):
        def pint(v):
            try:
                return int(v)
            except ValueError:
                return 0
        self.config.host = self.host_entry.get_text()
        self.config.ssh_port = pint(self.ssh_port_entry.get_text())
        self.config.port = pint(self.port_entry.get_text())
        self.config.username = self.username_entry.get_text()
        self.config.encoding = self.get_selected_encoding() or self.config.encoding
        mode_enc = self.mode_combo.get_active_text().upper()
        if mode_enc.startswith("TCP"):
            self.config.mode = "tcp"
            if mode_enc.find("AES")>0:
                self.config.encryption = "AES"
        elif mode_enc=="SSL":
            self.config.mode = "ssl"
        else:
            self.config.mode = "ssh"
        self.config.password = self.password_entry.get_text()
        log("update_options_from_gui() %s", (self.config.username, self.config.password, self.config.mode, self.config.encryption, self.config.host, self.config.port, self.config.ssh_port, self.config.encoding))

    def update_gui_from_config(self):
        #mode:
        mode = (self.config.mode or "").lower()
        for i,e in enumerate(self.get_connection_modes()):
            if e.lower()==mode:
                self.mode_combo.set_active(i)
        if self.config.encoding and self.encoding_combo:
            index = self.encoding_combo.get_menu().encoding_to_index.get(self.config.encoding, -1)
            log("setting encoding combo to %s / %s", self.config.encoding, index)
            #make sure the right one is the only one selected:
            for i,item in enumerate(self.encoding_combo.get_menu().get_children()):
                item.set_active(i==index)
            #then select it in the combo:
            if index>=0:
                self.encoding_combo.set_history(index)
        self.username_entry.set_text(self.config.username)
        self.password_entry.set_text(self.config.password)
        self.host_entry.set_text(self.config.host)
        def get_port(v, default_port=""):
            try:
                iport = int(v)
                if iport>0 and iport<2**16:
                    return str(iport)
            except:
                pass
            return str(default_port)
        dport = DEFAULT_PORT
        if mode=="ssh":
            #not required, so don't specify one
            dport = ""
        self.port_entry.set_text(get_port(self.config.port, dport))
        self.ssh_port_entry.set_text(get_port(self.config.ssh_port))

    def close_window(self, *_args):
        w = self.window
        if w:
            self.window = None
            w.destroy()

    def destroy(self, *args):
        log("destroy%s", args)
        self.close_window()
        gtk.main_quit()

    def update_options_from_URL(self, url):
        from xpra.scripts.parsing import parse_URL
        address, props = parse_URL(url)
        pa = address.split(":")
        if pa[0] in ("tcp", "ssh") and len(pa)>=2:
            props["mode"] = pa
            host = pa[1]
            ph = host.split("@", 1)
            if len(ph)==2:
                username, host = ph
                props["username"] = username
            props["host"] = host
            if len(pa)>=3:
                props["port"] = pa[2]
        self._apply_props(props)

    def update_options_from_file(self, filename):
        log("update_options_from_file(%s)", filename)
        props = read_config(filename)
        self._apply_props(props)

    def _apply_props(self, props):
        #we rely on "ssh_port" being defined on the config object
        #so try to load it from file, and define it if not present:
        options = validate_config(props, extras_types=LAUNCHER_OPTION_TYPES, extras_validation=self.get_launcher_validation())
        for k,v in options.items():
            fn = k.replace("-", "_")
            setattr(self.config, fn, v)
        self.config_keys = self.config_keys.union(set(props.keys()))
        log("_apply_props(%s) populated config with keys '%s', ssh=%s", props, options.keys(), self.config.ssh)

    def choose_session_file(self, title, action, action_button, callback):
        file_filter = gtk.FileFilter()
        file_filter.set_name("Xpra")
        file_filter.add_pattern("*.xpra")
        choose_file(self.window, title, action, action_button, callback, file_filter)

    def save_clicked(self, *_args):
        self.update_options_from_gui()
        def do_save(filename):
            #make sure the file extension is .xpra
            if os.path.splitext(filename)[-1]!=".xpra":
                filename += ".xpra"
            save_config(filename, self.config, self.config_keys, extras_types=LAUNCHER_OPTION_TYPES)
        self.choose_session_file("Save session settings to file", FILE_CHOOSER_ACTION_SAVE, gtk.STOCK_SAVE, do_save)

    def load_clicked(self, *_args):
        def do_load(filename):
            self.update_options_from_file(filename)
            self.update_gui_from_config()
        self.choose_session_file("Load session settings from file", FILE_CHOOSER_ACTION_OPEN, gtk.STOCK_OPEN, do_load)


#on some platforms like win32, we don't have stdout
#and this is a GUI application, so show a dialog with the error instead
def exception_dialog(title):
    md = gtk.MessageDialog(None, DESTROY_WITH_PARENT, MESSAGE_INFO,  BUTTONS_CLOSE, title)
    md.format_secondary_text(traceback.format_exc())
    md.show_all()
    def close_dialog(*_args):
        md.destroy()
        gtk.main_quit()
    md.connect("response", close_dialog)
    md.connect("close", close_dialog)
    gtk_main()


def main():
    from xpra.platform import program_context
    from xpra.log import enable_color
    with program_context("Xpra-Launcher", "Xpra Connection Launcher"):
        enable_color()
        return do_main()

def do_main():
    from xpra.os_util import SIGNAMES
    from xpra.scripts.main import InitExit, InitInfo
    from xpra.gtk_common.quit import gtk_main_quit_on_fatal_exceptions_enable
    gtk_main_quit_on_fatal_exceptions_enable()

    from xpra.platform.gui import ready as gui_ready
    gui_init()
    try:
        from xpra.scripts.parsing import parse_cmdline, fixup_debug_option
        options, args = parse_cmdline(sys.argv)
        debug = fixup_debug_option(options.debug)
        if debug:
            for x in debug.split(","):
                enable_debug_for(x)
    except InitInfo as e:
        print(str(e))
        return 0
    except InitExit as e:
        return e.status
    except Exception:
        exception_dialog("Error parsing command line")
        return 1

    #allow config to be debugged:
    from xpra.scripts import config
    config.debug = log.debug

    try:
        app = ApplicationWindow()
        def app_signal(signum, _frame):
            print("")
            log("got signal %s" % SIGNAMES.get(signum, signum))
            def show_signal():
                app.show()
                app.client.cleanup()
                glib.timeout_add(1000, app.set_info_text, "got signal %s" % SIGNAMES.get(signum, signum))
                glib.timeout_add(1000, app.set_info_color, True)
            #call from UI thread:
            glib.idle_add(show_signal)
        if sys.version_info[0]<3:
            #breaks GTK3..
            signal.signal(signal.SIGINT, app_signal)
        signal.signal(signal.SIGTERM, app_signal)
        has_file = len(args) == 1
        if has_file:
            app.update_options_from_file(args[0])
            #the compressors and packet encoders cannot be changed from the UI
            #so apply them now:
            configure_network(app.config)
        debug = fixup_debug_option(app.config.debug)
        if debug:
            for x in debug.split(","):
                enable_debug_for(x)
        #suspend tray workaround for our window widgets:
        try:
            set_use_tray_workaround(False)
            app.create_window()
        finally:
            set_use_tray_workaround(True)
        app.update_gui_from_config()
    except Exception:
        exception_dialog("Error creating launcher form")
        return 1
    try:
        if app.config.autoconnect:
            #file says we should connect,
            #do that only (not showing UI unless something goes wrong):
            glib.idle_add(app.do_connect)
        if not has_file:
            app.reset_errors()
        gui_ready()
        if not app.config.autoconnect or app.config.debug:
            #FIXME: this is ugly as hell
            #We have to wait for the main loop to be running
            #to get the NSApplicationOpneFile signal,
            #so we end up duplicating some of the logic from just above
            #maybe we should always run this code from the main loop instead
            if OSX:
                def force_show():
                    from xpra.platform.darwin.gui import enable_focus_workaround, disable_focus_workaround
                    enable_focus_workaround()
                    app.show()
                    glib.timeout_add(500, disable_focus_workaround)
                #wait a little bit for the "openFile" signal
                app.__osx_open_signal = False
                def do_open_file(filename):
                    log.info("do_open_file(%s)", filename)
                    app.update_options_from_file(filename)
                    #the compressors and packet encoders cannot be changed from the UI
                    #so apply them now:
                    configure_network(app.config)
                    app.update_gui_from_config()
                    if app.config.autoconnect:
                        app.__osx_open_signal = True
                        glib.idle_add(app.do_connect)
                    else:
                        force_show()
                def open_file(_, filename):
                    log.info("open_file(%s)", filename)
                    glib.idle_add(do_open_file, filename)
                def do_open_URL(url):
                    log.info("do_open_URL(%s)", url)
                    app.__osx_open_signal = True
                    app.update_options_from_URL(url)
                    #the compressors and packet encoders cannot be changed from the UI
                    #so apply them now:
                    configure_network(app.config)
                    app.update_gui_from_config()
                    glib.idle_add(app.do_connect)
                def open_URL(url):
                    log.info("open_URL(%s)", url)
                    glib.idle_add(do_open_URL, url)
                from xpra.platform.darwin.gui import get_OSXApplication, register_URL_handler
                register_URL_handler(open_URL)
                try:
                    get_OSXApplication().connect("NSApplicationOpenFile", open_file)
                except Exception as e:
                    log.error("Error: cannot handle file associations:")
                    log.error(" %s", e)
                def may_show():
                    log("may_show() osx open signal=%s", app.__osx_open_signal)
                    if not app.__osx_open_signal:
                        force_show()
                glib.timeout_add(500, may_show)
            else:
                app.show()
        app.run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    v = main()
    sys.exit(v)
