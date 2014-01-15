#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2009-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

""" client_launcher.py

This is a simple GUI for starting the xpra client.

"""

import os.path
import sys
import shlex
import signal

import pygtk
pygtk.require('2.0')
import gtk
from gtk import gdk
import gobject
gobject.threads_init()
import pango


from xpra.gtk_common.quit import gtk_main_quit_on_fatal_exceptions_enable
gtk_main_quit_on_fatal_exceptions_enable()
from xpra.scripts.config import read_config, make_defaults_struct, validate_config, save_config
from xpra.codecs.loader import PREFERED_ENCODING_ORDER
from xpra.gtk_common.gtk_util import set_tooltip_text, add_close_accel, scaled_image
from xpra.os_util import set_prgname, thread
from xpra.client.gtk_base.gtk_tray_menu_base import make_min_auto_menu, make_encodingsmenu, MIN_QUALITY_OPTIONS, QUALITY_OPTIONS, MIN_SPEED_OPTIONS, SPEED_OPTIONS
from xpra.client.gtk_base.about import about
from xpra.client.client_base import SIGNAMES
from xpra.scripts.main import connect_to, make_client
from xpra.platform import init as platform_init
from xpra.platform.gui import init as gui_init, ready as gui_ready
from xpra.platform.paths import get_icon_dir
from xpra.log import Logger
log = Logger()


black = gdk.color_parse("black")
red = gdk.color_parse("red")
white = gdk.color_parse("white")


def get_active_item_index(optionmenu):
    i = 0
    menu = optionmenu.get_menu()
    for x in menu.get_children():
        if hasattr(x, "get_active") and x.get_active():
            return i
        i += 1
    return -1

def set_history_from_active(optionmenu):
    #Used for OptionMenu combo:
    #sets the first active menu entry as the "history" value (the selected item)
    i = get_active_item_index(optionmenu)
    if i>0:
        optionmenu.set_history(i)


class ApplicationWindow:

    def    __init__(self):
        # Default connection options
        self.config = make_defaults_struct()
        #what we save by default:
        self.config_keys = set(["username", "password", "host", "port", "mode",
                                "encoding", "quality", "min-quality", "speed", "min-speed"])
        self.config.client_toolkit = "gtk2"
        self.client = make_client(Exception, self.config)
        self.exit_code = None

    def create_window(self):
        self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
        self.window.connect("destroy", self.destroy)
        self.window.set_default_size(400, 300)
        self.window.set_border_width(20)
        self.window.set_title("Xpra Launcher")
        self.window.modify_bg(gtk.STATE_NORMAL, gdk.Color(red=65535, green=65535, blue=65535))

        icon_pixbuf = self.get_icon("xpra.png")
        if icon_pixbuf:
            self.window.set_icon(icon_pixbuf)
        self.window.set_position(gtk.WIN_POS_CENTER)

        vbox = gtk.VBox(False, 0)
        vbox.set_spacing(15)

        # Title
        hbox = gtk.HBox(False, 0)
        if icon_pixbuf:
            logo_button = gtk.Button("")
            settings = logo_button.get_settings()
            settings.set_property('gtk-button-images', True)
            logo_button.connect("clicked", about)
            set_tooltip_text(logo_button, "About")
            image = gtk.Image()
            image.set_from_pixbuf(icon_pixbuf)
            logo_button.set_image(image)
            hbox.pack_start(logo_button, expand=False, fill=False)
        label = gtk.Label("Connect to xpra server")
        label.modify_font(pango.FontDescription("sans 14"))
        hbox.pack_start(label, expand=True, fill=True)
        vbox.pack_start(hbox)

        # Mode:
        hbox = gtk.HBox(False, 20)
        hbox.set_spacing(20)
        hbox.pack_start(gtk.Label("Mode: "))
        self.mode_combo = gtk.combo_box_new_text()
        self.mode_combo.get_model().clear()
        self.mode_combo.append_text("TCP")
        self.mode_combo.append_text("TCP + AES")
        self.mode_combo.append_text("SSH")
        self.mode_combo.connect("changed", self.mode_changed)
        hbox.pack_start(self.mode_combo)
        vbox.pack_start(hbox)

        # Encoding:
        hbox = gtk.HBox(False, 20)
        hbox.set_spacing(20)
        hbox.pack_start(gtk.Label("Encoding: "))
        self.encoding_combo = gtk.OptionMenu()
        def get_current_encoding():
            return self.config.encoding
        def set_new_encoding(e):
            self.config.encoding = e
        encodings = [x for x in PREFERED_ENCODING_ORDER if x in self.client.get_encodings()]
        server_encodings = encodings
        es = make_encodingsmenu(get_current_encoding, set_new_encoding, encodings, server_encodings)
        self.encoding_combo.set_menu(es)
        set_history_from_active(self.encoding_combo)
        hbox.pack_start(self.encoding_combo)
        vbox.pack_start(hbox)
        self.encoding_combo.connect("changed", self.encoding_changed)

        # Quality
        hbox = gtk.HBox(False, 20)
        hbox.set_spacing(20)
        self.quality_label = gtk.Label("Quality: ")
        hbox.pack_start(self.quality_label)
        self.quality_combo = gtk.OptionMenu()
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
        vbox.pack_start(hbox)

        # Speed
        hbox = gtk.HBox(False, 20)
        hbox.set_spacing(20)
        self.speed_label = gtk.Label("Speed: ")
        hbox.pack_start(self.speed_label)
        self.speed_combo = gtk.OptionMenu()
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
        vbox.pack_start(hbox)

        # Username@Host:Port
        hbox = gtk.HBox(False, 0)
        hbox.set_spacing(5)
        self.username_entry = gtk.Entry(max=128)
        self.username_entry.set_width_chars(16)
        self.username_entry.connect("changed", self.validate)
        set_tooltip_text(self.username_entry, "SSH username")
        self.username_label = gtk.Label("@")
        self.host_entry = gtk.Entry(max=128)
        self.host_entry.set_width_chars(24)
        self.host_entry.connect("changed", self.validate)
        set_tooltip_text(self.host_entry, "hostname")
        self.port_entry = gtk.Entry(max=5)
        self.port_entry.set_width_chars(5)
        self.port_entry.connect("changed", self.validate)
        hbox.pack_start(self.username_entry)
        hbox.pack_start(self.username_label)
        hbox.pack_start(self.host_entry)
        hbox.pack_start(gtk.Label(":"))
        hbox.pack_start(self.port_entry)
        vbox.pack_start(hbox)

        # Password
        hbox = gtk.HBox(False, 0)
        hbox.set_spacing(20)
        self.password_entry = gtk.Entry(max=128)
        self.password_entry.set_width_chars(30)
        self.password_entry.set_text("")
        self.password_entry.set_visibility(False)
        self.password_entry.connect("changed", self.password_ok)
        self.password_entry.connect("changed", self.validate)
        self.password_label = gtk.Label("Password: ")
        hbox.pack_start(self.password_label)
        hbox.pack_start(self.password_entry)
        vbox.pack_start(hbox)

        # Info Label
        self.info = gtk.Label()
        self.info.set_line_wrap(True)
        self.info.set_size_request(360, -1)
        self.info.modify_fg(gtk.STATE_NORMAL, red)
        vbox.pack_start(self.info)

        # Buttons:
        hbox = gtk.HBox(False, 20)
        vbox.pack_start(hbox)
        #Save:
        self.save_btn = gtk.Button("Save")
        set_tooltip_text(self.save_btn, "Save settings to a session file")
        self.save_btn.connect("clicked", self.save_clicked)
        hbox.pack_start(self.save_btn)
        #Load:
        self.load_btn = gtk.Button("Load")
        set_tooltip_text(self.load_btn, "Load settings from a session file")
        self.load_btn.connect("clicked", self.load_clicked)
        hbox.pack_start(self.load_btn)
        # Connect button:
        self.button = gtk.Button("Connect")
        self.button.connect("clicked", self.connect_clicked)
        connect_icon = self.get_icon("retry.png")
        if connect_icon:
            self.button.set_image(scaled_image(connect_icon, 24))
        hbox.pack_start(self.button)

        def accel_close(*args):
            gtk.main_quit()
        add_close_accel(self.window, accel_close)
        vbox.show_all()
        self.window.vbox = vbox
        self.window.add(vbox)

    def validate(self, *args):
        ssh = self.mode_combo.get_active_text()=="SSH"
        errs = []
        host = self.host_entry.get_text()
        errs.append((self.host_entry, not bool(host), "specify the host"))
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
        log.debug("validate(%s) err_text=%s, errs=%s", args, err_text, errs)
        self.set_info_text(", ".join(err_text))
        self.set_info_color(len(err_text)>0)
        self.button.set_sensitive(len(err_text)==0)
        return errs

    def show(self):
        self.window.show()
        self.window.present()

    def run(self):
        from xpra.gtk_common.gtk2common import gtk2main
        gtk2main()

    def get_icon(self, icon_name):
        icon_filename = os.path.join(get_icon_dir(), icon_name)
        if os.path.exists(icon_filename):
            return gdk.pixbuf_new_from_file(icon_filename)
        return None

    def mode_changed(self, *args):
        ssh = self.mode_combo.get_active_text()=="SSH"
        self.port_entry.set_text("")
        if ssh:
            set_tooltip_text(self.port_entry, "Display number")
            set_tooltip_text(self.password_entry, "SSH Password")
            self.username_entry.show()
            self.username_label.show()
        else:
            set_tooltip_text(self.port_entry, "port number")
            set_tooltip_text(self.password_entry, "Session Password")
            self.username_entry.hide()
            self.username_label.hide()
            if self.config.port>0:
                self.port_entry.set_text("%s" % self.config.port)
        if not ssh or sys.platform.startswith("win") or sys.platform.startswith("darwin"):
            #password cannot be used with ssh
            #(except on win32 with plink, and on osx via the SSH_ASKPASS hack)
            self.password_label.show()
            self.password_entry.show()
        else:
            self.password_label.hide()
            self.password_entry.hide()
        self.validate()

    def get_selected_encoding(self, *args):
        index = get_active_item_index(self.encoding_combo)
        return self.encoding_combo.get_menu().index_to_encoding.get(index)

    def encoding_changed(self, *args):
        encoding = self.get_selected_encoding()
        log("encoding_changed(%s) encoding=%s", args, encoding)
        uses_quality_option = encoding in ["jpeg", "webp", "h264"]
        if uses_quality_option:
            self.quality_combo.show()
            self.quality_label.show()
        else:
            self.quality_combo.hide()
            self.quality_label.hide()

    def reset_errors(self):
        self.set_sensitive(True)
        self.set_info_text("")
        for widget in (self.info, self.password_entry, self.username_entry, self.host_entry, self.port_entry):
            self.set_widget_fg_color(self.info, False)
            self.set_widget_bg_color(widget, False)

    def set_info_text(self, text):
        if self.info:
            gobject.idle_add(self.info.set_text, text)

    def set_info_color(self, is_error=False):
        self.set_widget_fg_color(self.info, is_error)


    def set_sensitive(self, s):
        gobject.idle_add(self.window.set_sensitive, s)

    def connect_clicked(self, *args):
        self.update_options_from_gui()
        self.do_connect()

    def handle_exception(self, e):
        def ui_handle_exception():
            self.set_sensitive(True)
            self.set_info_color(True)
            self.set_info_text(str(e))
            self.window.show()
        gobject.idle_add(ui_handle_exception)

    def do_connect(self):
        try:
            self.connect_builtin()
        except Exception, e:
            log.error("cannot connect:", exc_info=True)
            self.handle_exception(e)

    def connect_builtin(self):
        #cooked vars used by connect_to
        params = {"type"    : self.config.mode}
        if self.config.mode=="ssh":
            remote_xpra = self.config.remote_xpra.split()
            if self.config.socket_dir:
                remote_xpra.append("--socket-dir=%s" % self.config.socket_dir)
            params["remote_xpra"] = remote_xpra
            params["proxy_command"] = ["_proxy"]
            if self.config.port and self.config.port>0:
                params["display"] = ":%s" % self.config.port
                params["display_as_args"] = [params["display"]]
            else:
                params["display"] = "auto"
                params["display_as_args"] = []
            full_ssh = shlex.split(self.config.ssh)
            password = self.config.password
            username = self.config.username
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
            params["full_ssh"] = full_ssh
            params["password"] = password
            params["display_name"] = "ssh:%s:%s" % (self.config.host, self.config.port)
        elif self.config.mode=="unix-domain":
            params["display"] = ":%s" % self.config.port
            params["display_name"] = "unix-domain:%s" % self.config.port
        else:
            #tcp:
            params["host"] = self.config.host
            params["port"] = int(self.config.port)
            params["display_name"] = "tcp:%s:%s" % (self.config.host, self.config.port)

        #print("connect_to(%s)" % params)
        self.set_info_text("Connecting...")
        thread.start_new_thread(self.do_connect_builtin, (params,))

    def ssh_failed(self, message):
        self.set_info_text(message)
        self.set_info_color(True)

    def do_connect_builtin(self, params):
        self.exit_code = None
        self.set_info_text("Connecting.")
        self.set_sensitive(False)
        try:
            conn = connect_to(params, self.set_info_text, ssh_fail_cb=self.ssh_failed)
        except Exception, e:
            log.error("failed to connect", exc_info=True)
            self.handle_exception(e)
            return
        gobject.idle_add(self.window.hide)
        gobject.idle_add(self.start_XpraClient, conn)

    def start_XpraClient(self, conn):
        try:
            self.do_start_XpraClient(conn)
        except Exception, e:
            log.error("failed to start client", exc_info=True)
            self.handle_exception(e)

    def do_start_XpraClient(self, conn):
        log("start_XpraClient() client=%s", self.client)
        self.client.setup_connection(conn)
        self.client.init(self.config)
        log("start_XpraClient() client initialized")

        if self.config.password:
            #pass the password to the class directly:
            self.client.password = self.config.password
        #override exit code:
        warn_and_quit_save = self.client.warn_and_quit
        quit_save = self.client.quit
        def do_quit(*args):
            self.client.warn_and_quit = warn_and_quit_save
            self.client.quit = quit_save
            self.destroy()
            gtk.main_quit()
        def warn_and_quit_override(exit_code, warning):
            log("warn_and_quit_override(%s, %s)", exit_code, warning)
            if self.exit_code == None:
                self.exit_code = exit_code
            self.client.cleanup()
            password_warning = warning.find("invalid password")>=0
            if password_warning:
                self.password_warning()
            err = exit_code!=0 or password_warning
            self.set_info_color(err)
            self.set_info_text(warning)
            if err:
                def ignore_further_quit_events(*args):
                    pass
                self.client.warn_and_quit = ignore_further_quit_events
                self.client.quit = ignore_further_quit_events
                self.set_sensitive(True)
                gobject.idle_add(self.window.show)
            else:
                do_quit()

        def quit_override(exit_code):
            log("quit_override(%s)", exit_code)
            if self.exit_code == None:
                self.exit_code = exit_code
            self.client.cleanup()
            if self.exit_code==0:
                do_quit()

        self.client.warn_and_quit = warn_and_quit_override
        self.client.quit = quit_override
        try:
            self.client.run()
        except Exception, e:
            log.error("client error", exc_info=True)
            self.handle_exception(e)

    def password_ok(self, *args):
        self.password_entry.modify_text(gtk.STATE_NORMAL, black)

    def password_warning(self, *args):
        self.password_entry.modify_text(gtk.STATE_NORMAL, red)
        self.password_entry.grab_focus()

    def set_widget_bg_color(self, widget, is_error=False):
        if is_error:
            color_obj = red
        else:
            color_obj = white
        if color_obj:
            gobject.idle_add(widget.modify_base, gtk.STATE_NORMAL, color_obj)

    def set_widget_fg_color(self, widget, is_error=False):
        if is_error:
            color_obj = red
        else:
            color_obj = black
        if color_obj:
            gobject.idle_add(widget.modify_fg, gtk.STATE_NORMAL, color_obj)


    def update_options_from_gui(self):
        self.config.host = self.host_entry.get_text()
        self.config.port = self.port_entry.get_text()
        self.config.username = self.username_entry.get_text()
        self.config.encoding = self.get_selected_encoding()
        mode_enc = self.mode_combo.get_active_text()
        if mode_enc.startswith("TCP"):
            self.config.mode = "tcp"
            if mode_enc.find("AES")>0:
                self.config.encryption = "AES"
        else:
            self.config.mode = "ssh"
        self.config.password = self.password_entry.get_text()

    def update_gui_from_config(self):
        #mode:
        if self.config.mode == "tcp":
            self.mode_combo.set_active(0)
        elif self.config.mode == "tcp + aes":
            self.mode_combo.set_active(1)
        else:
            self.mode_combo.set_active(2)
        if self.config.encoding:
            index = self.encoding_combo.get_menu().encoding_to_index.get(self.config.encoding, -1)
            if index>0:
                self.encoding_combo.set_history(index)
        self.username_entry.set_text(self.config.username)
        self.password_entry.set_text(self.config.password)
        self.host_entry.set_text(self.config.host)
        port = ""
        try:
            iport = int(self.config.port)
            if iport>0:
                port = str(iport)
        except:
            pass
        self.port_entry.set_text(port)

    def destroy(self, *args):
        self.window.destroy()
        self.window = None
        gtk.main_quit()

    def update_options_from_file(self, filename):
        props = read_config(filename)
        options = validate_config(props)
        for k,v in options.items():
            fn = k.replace("-", "_")
            setattr(self.config, fn, v)
        self.config_keys = self.config_keys.union(set(props.keys()))

    def choose_session_file(self, title, action, action_button, callback):
        log("choose_session_file(%s, %s)", title, callback)
        chooser = gtk.FileChooserDialog(title,
                                    parent=self.window, action=action,
                                    buttons=(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, action_button, gtk.RESPONSE_OK))
        chooser.set_select_multiple(False)
        chooser.set_default_response(gtk.RESPONSE_OK)
        file_filter = gtk.FileFilter()
        file_filter.set_name("Xpra")
        file_filter.add_pattern("*.xpra")
        chooser.add_filter(file_filter)
        response = chooser.run()
        filenames = chooser.get_filenames()
        chooser.hide()
        chooser.destroy()
        if response!=gtk.RESPONSE_OK or len(filenames)!=1:
            return
        filename = filenames[0]
        callback(filename)

    def save_clicked(self, *args):
        self.update_options_from_gui()
        def do_save(filename):
            save_config(filename, self.config, self.config_keys)
        self.choose_session_file("Save session settings to file", gtk.FILE_CHOOSER_ACTION_SAVE, gtk.STOCK_SAVE, do_save)

    def load_clicked(self, *args):
        def do_load(filename):
            self.update_options_from_file(filename)
            self.update_gui_from_config()
        self.choose_session_file("Load session settings from file", gtk.FILE_CHOOSER_ACTION_OPEN, gtk.STOCK_OPEN, do_load)


def main():
    if sys.platform.startswith("win"):
        from xpra.platform.win32 import set_log_filename
        set_log_filename("Xpra-Launcher.log")
    set_prgname("Xpra-Launcher")
    platform_init()
    gui_init()

    #logging init:
    from xpra.scripts.main import parse_cmdline
    _, options, args = parse_cmdline(sys.argv)
    import logging
    logging.basicConfig(format="%(asctime)s %(message)s")
    if options.debug:
        logging.root.setLevel(logging.DEBUG)
    else:
        logging.root.setLevel(logging.INFO)

    app = ApplicationWindow()
    def app_signal(signum, frame):
        print("")
        log("got signal %s" % SIGNAMES.get(signum, signum))
        def show_signal():
            app.show()
            app.client.cleanup()
            gobject.timeout_add(1000, app.set_info_text, "got signal %s" % SIGNAMES.get(signum, signum))
            gobject.timeout_add(1000, app.set_info_color, True)
        #call from UI thread:
        gobject.idle_add(show_signal)
    signal.signal(signal.SIGINT, app_signal)
    signal.signal(signal.SIGTERM, app_signal)
    has_file = len(args) == 1
    if has_file:
        app.update_options_from_file(args[0])
    if app.config.debug:
        logging.root.setLevel(logging.DEBUG)
    app.create_window()
    try:
        app.update_gui_from_config()
        if app.config.autoconnect:
            #file says we should connect,
            #do that only (not showing UI unless something goes wrong):
            gobject.idle_add(app.do_connect)
        if not has_file:
            app.reset_errors()
        gui_ready()
        if not app.config.autoconnect or app.config.debug:
            app.show()
        app.run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    v = main()
    sys.exit(v)
