# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017-2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path
import socket
import subprocess

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Pango", "1.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Pango, GLib, Gtk, GdkPixbuf, Gio

from xpra.platform.paths import get_icon_dir, get_xpra_command, get_nodock_command
from xpra.platform.dotxpra import DotXpra
from xpra.platform.gui import force_focus
from xpra.child_reaper import getChildReaper
from xpra.exit_codes import EXIT_STR
from xpra.gtk_common.gtk_util import (
    add_close_accel, TableBuilder, scaled_image, color_parse,
    imagebutton,
    )
from xpra.gtk_common.gobject_compat import register_os_signals
from xpra.net.net_util import if_indextoname
from xpra.util import typedict, DEFAULT_PORTS
from xpra.os_util import bytestostr, WIN32
from xpra.log import Logger

log = Logger("client", "util")


def get_pixbuf(icon_name):
    icon_filename = os.path.join(get_icon_dir(), icon_name)
    if os.path.exists(icon_filename):
        return GdkPixbuf.Pixbuf.new_from_file(icon_filename)
    return None

class SessionsGUI(Gtk.Window):

    def __init__(self, options, title="Xpra Session Browser"):
        Gtk.Window.__init__(self)
        self.exit_code = 0
        self.set_title(title)
        self.set_border_width(20)
        self.set_resizable(True)
        self.set_default_size(800, 220)
        self.set_decorated(True)
        self.set_size_request(800, 220)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_wmclass("xpra-sessions-gui", "Xpra-Sessions-GUI")
        add_close_accel(self, self.quit)
        self.connect("delete_event", self.quit)
        icon = get_pixbuf("browse.png")
        if icon:
            self.set_icon(icon)

        hb = Gtk.HeaderBar()
        hb.set_show_close_button(True)
        hb.props.title = "Xpra"
        button = Gtk.Button()
        icon = Gio.ThemedIcon(name="help-about")
        image = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)
        button.add(image)
        button.set_tooltip_text("About")
        button.connect("clicked", self.show_about)
        hb.add(button)
        hb.show_all()
        self.set_titlebar(hb)

        self.clients = {}
        self.clients_disconnecting = set()
        self.child_reaper = getChildReaper()

        self.vbox = Gtk.VBox(False, 20)
        self.add(self.vbox)

        title_label = Gtk.Label(title)
        title_label.modify_font(Pango.FontDescription("sans 14"))
        title_label.show()
        self.vbox.add(title_label)

        self.warning = Gtk.Label(" ")
        red = color_parse("red")
        self.warning.modify_fg(Gtk.StateType.NORMAL, red)
        self.warning.show()
        self.vbox.add(self.warning)

        self.password_box = Gtk.HBox(False, 10)
        self.password_label = Gtk.Label("Password:")
        al = Gtk.Alignment(xalign=1, yalign=0.5)
        al.add(self.password_label)
        al.show()
        self.password_box.add(al)
        self.password_entry = Gtk.Entry()
        self.password_entry.set_max_length(128)
        self.password_entry.set_width_chars(16)
        self.password_entry.set_visibility(False)
        al = Gtk.Alignment(xalign=0, yalign=0.5)
        al.add(self.password_entry)
        al.show()
        self.password_box.add(al)
        self.vbox.add(self.password_box)

        self.table = None
        self.records = []
        try:
            from xpra.platform.info import get_username
            username = get_username()
        except Exception:
            username = ""
        #log.info("options=%s (%s)", options, type(options))
        self.local_info_cache = {}
        self.dotxpra = DotXpra(options.socket_dir, options.socket_dirs, username)
        self.poll_local_sessions()
        self.populate()
        GLib.timeout_add(5*1000, self.update)
        self.vbox.show()
        self.show()

    def show(self):
        super().show()
        def show():
            force_focus()
            self.present()
        GLib.idle_add(show)

    def quit(self, *args):
        log("quit%s", args)
        self.do_quit()

    def do_quit(self):
        log("do_quit()")
        self.cleanup()
        Gtk.main_quit()

    def app_signal(self, signum):
        self.exit_code = 128 + signum
        log("app_signal(%s) exit_code=%i", signum, self.exit_code)
        self.do_quit()

    def cleanup(self):
        self.destroy()


    def show_about(self, *_args):
        from xpra.gtk_common.about import about
        about()


    def update(self):
        if self.poll_local_sessions():
            self.populate()
        return True

    def populate(self):
        self.populate_table()

    def poll_local_sessions(self):
        #TODO: run in a thread so we don't block the UI thread!
        d = self.dotxpra.socket_details(matching_state=DotXpra.LIVE)
        log("poll_local_sessions() socket_details=%s", d)
        info_cache = {}
        for d, details in d.items():
            log("poll_local_sessions() %s : %s", d, details)
            for state, display, sockpath in details:
                assert state==DotXpra.LIVE
                key = (display, sockpath)
                info = self.local_info_cache.get(key)
                if not info:
                    #try to query it
                    try:
                        info = self.get_session_info(sockpath)
                    except Exception as e:
                        log("get_session_info(%s)", sockpath, exc_info=True)
                        log.error("Error querying session info for %s", sockpath)
                        log.error(" %s", e)
                        del e
                    if not info:
                        continue
                #log("info(%s)=%s", sockpath, repr_ellipsized(str(info)))
                info_cache[key] = info
        def make_text(info):
            text = {"mode" : "socket"}
            for k, name in {
                "platform"       : "platform",
                "uuid"           : "uuid",
                "display"        : "display",
                "session-type"   : "type",
                "session-name"   : "name",
                }.items():
                v = info.get(k)
                if v is not None:
                    text[name] = v
            return text
        #first remove any records that are no longer found:
        for key in self.local_info_cache:
            if key not in info_cache:
                display, sockpath = key
                self.records = [(interface, protocol, name, stype, domain, host, address, port, text) for
                                (interface, protocol, name, stype, domain, host, address, port, text) in self.records
                                if (protocol!="socket" or domain!="local" or address!=sockpath)]
        #add the new ones:
        for key, info in info_cache.items():
            if key not in self.local_info_cache:
                display, sockpath = key
                self.records.append(("", "socket", "", "", "local", socket.gethostname(), sockpath, 0, make_text(info)))
        log("poll_local_sessions() info_cache=%s", info_cache)
        changed = self.local_info_cache!=info_cache
        self.local_info_cache = info_cache
        return changed

    def get_session_info(self, sockpath):
        #the lazy way using a subprocess
        if WIN32:
            socktype = "namedpipe"
        else:
            socktype = "socket"
        cmd = get_nodock_command()+["id", "%s:%s" % (socktype, sockpath)]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout = p.communicate()[0]
        log("get_sessions_info(%s) returncode(%s)=%s", sockpath, cmd, p.returncode)
        if p.returncode!=0:
            return None
        out = bytestostr(stdout)
        info = {}
        for line in out.splitlines():
            parts = line.split("=", 1)
            if len(parts)==2:
                info[parts[0]] = parts[1]
        log("get_sessions_info(%s)=%s", sockpath, info)
        return info


    def populate_table(self):
        log("populate_table: %i records", len(self.records))
        if self.table:
            self.vbox.remove(self.table)
            self.table = None
        if not self.records:
            self.table = Gtk.Label("No sessions found")
            self.vbox.add(self.table)
            self.table.show()
            self.set_size_request(440, 200)
            self.password_box.hide()
            return
        self.password_box.show()
        self.set_size_request(-1, -1)
        tb = TableBuilder(1, 6, False)
        labels = [Gtk.Label(x) for x in (
            "Host", "Display", "Name", "Platform", "Type", "URI", "Connect", "Open in Browser",
            )]
        tb.add_row(*labels)
        self.table = tb.get_table()
        self.vbox.add(self.table)
        self.table.resize(1+len(self.records), 5)
        #group them by uuid
        d = {}
        session_names = {}
        for i, record in enumerate(self.records):
            interface, protocol, name, stype, domain, host, address, port, text = record
            td = typedict(text)
            log("populate_table: record[%i]=%s", i, record)
            uuid = td.strget("uuid", "")
            display = td.strget("display", "")
            if domain=="local" and host.endswith(".local"):
                host = host[:-len(".local")]
            if uuid:
                key = uuid
            else:
                key = (host, display)
            log("populate_table: key[%i]=%s", i, key)
            d.setdefault(key, []).append((interface, protocol, name, stype, domain, host, address, port, text))
            #older servers expose the "session-name" as "session":
            td = typedict(text)
            session_name = td.strget("name", "") or td.strget("session", "")
            if session_name:
                session_names[key] = session_name
        for key, recs in d.items():
            if isinstance(key, tuple):
                host, display = key
            else:
                uuid = key
                host, platform, dtype = None, sys.platform, None
                #try to find a valid host name:
                hosts = [rec[5] for rec in recs if not rec[5].startswith("local")]
                if not hosts:
                    hosts = [rec[5] for rec in recs]
                host = hosts[0]
            platform, dtype = None, None
            for rec in recs:
                td = typedict(rec[-1])
                if not platform:
                    platform = td.strget("platform", "")
                if not dtype:
                    dtype = td.strget("type", "")
            title = uuid
            if display:
                title = display
            label = Gtk.Label(title)
            if uuid!=title:
                label.set_tooltip_text(uuid)
            #try to use an icon for the platform:
            platform_icon_name = self.get_platform_icon_name(platform)
            pwidget = None
            if platform_icon_name:
                pwidget = scaled_image(self.get_pixbuf("%s.png" % platform_icon_name), 28)
                if pwidget:
                    pwidget.set_tooltip_text(platform_icon_name)
            if not pwidget:
                pwidget = Gtk.Label(platform)
            w, c, b = self.make_connect_widgets(key, recs, address, port, display)
            session_name = session_names.get(key, "")
            tb.add_row(Gtk.Label(host), label, Gtk.Label(session_name), pwidget, Gtk.Label(dtype), w, c, b)
        self.table.show_all()

    def get_uri(self, password, interface, protocol, name, stype, domain, host, address, port, text):
        dstr = ""
        tt = typedict(text)
        display = tt.strget("display", "")
        username = tt.strget("username", "")
        mode = tt.strget("mode", "")
        if not mode:
            #guess the mode from the service name,
            #ie: "localhost.localdomain :2 (wss)" -> "wss"
            #ie: "localhost.localdomain :2 (ssh-2)" -> "ssh"
            pos = name.rfind("(")
            if name.endswith(")") and pos>0:
                mode = name[pos+1:-1].split("-")[0]
                if mode not in ("tcp", "ws", "wss", "ssl", "ssh"):
                    return ""
            else:
                mode = "tcp"
        if display and display.startswith(":"):
            dstr = display[1:]
        #append interface to IPv6 host URI for link local addresses ("fe80:"):
        if interface and if_indextoname and address.lower().startswith("fe80:"):
            #ie: "fe80::c1:ac45:7351:ea69%eth1"
            address += "%%%s" % if_indextoname(interface)
        if username:
            if password:
                uri = "%s://%s:%s@%s" % (mode, username, password, address)
            else:
                uri = "%s://%s@%s" % (mode, username, address)
        else:
            uri = "%s://%s" % (mode, address)
        if port>0 and DEFAULT_PORTS.get(mode, 0)!=port:
            uri += ":%s" % port
        if protocol not in ("socket", "namedpipe"):
            uri += "/"
            if dstr:
                uri += "%s" % dstr
        return uri

    def attach(self, key, uri):
        self.warning.set_text("")
        cmd = get_xpra_command() + ["attach", uri]
        env = os.environ.copy()
        env["XPRA_NOTTY"] = "1"
        proc = subprocess.Popen(cmd, env=env)
        log("attach() Popen(%s)=%s", cmd, proc)
        def proc_exit(*args):
            log("proc_exit%s", args)
            c = proc.poll()
            if key in self.clients_disconnecting:
                self.clients_disconnecting.remove(key)
            elif c not in (0, None):
                self.warning.set_text(EXIT_STR.get(c, "exit code %s" % c).replace("_", " "))
            try:
                del self.clients[key]
            except KeyError:
                pass
            else:
                def update():
                    self.update()
                    self.populate()
                GLib.idle_add(update)
        self.child_reaper.add_process(proc, "client-%s" % uri, cmd, True, True, proc_exit)
        self.clients[key] = proc
        self.populate()

    def browser_open(self, rec):
        import webbrowser
        password = self.password_entry.get_text()
        url = self.get_uri(password, *rec)
        if url.startswith("wss"):
            url = "https"+url[3:]
        else:
            assert url.startswith("ws")
            url = "http"+url[2:]
        #trim end of URL:
        #http://192.168.1.7:10000/10 -> http://192.168.1.7:10000/
        url = url[:url.rfind("/")]
        webbrowser.open_new_tab(url)

    def make_connect_widgets(self, key, recs, address, port, display):
        d = {}
        proc = self.clients.get(key)
        if proc and proc.poll() is None:
            icon = self.get_pixbuf("disconnected.png")
            def disconnect_client(btn):
                log("disconnect_client(%s) proc=%s", btn, proc)
                self.clients_disconnecting.add(key)
                proc.terminate()
                self.populate()
            btn = imagebutton("Disconnect", icon, clicked_callback=disconnect_client)
            return Gtk.Label("Already connected with pid=%i" % proc.pid), btn, Gtk.Label("")

        icon = self.get_pixbuf("browser.png")
        bopen = imagebutton("Open", icon)

        icon = self.get_pixbuf("connect.png")
        if len(recs)==1:
            #single record, single uri:
            rec = recs[0]
            uri = self.get_uri(None, *rec)
            bopen.set_sensitive(uri.startswith("ws"))
            def browser_open(*_args):
                self.browser_open(rec)
            bopen.connect("clicked", browser_open)
            d[uri] = rec
            def clicked(*_args):
                password = self.password_entry.get_text()
                uri = self.get_uri(password, *rec)
                self.attach(key, uri)
            btn = imagebutton("Connect", icon, clicked_callback=clicked)
            return Gtk.Label(uri), btn, bopen

        #multiple modes / uris
        uri_menu = Gtk.ComboBoxText()
        uri_menu.set_size_request(340, 48)
        #sort by protocol so TCP comes first
        order = {"socket" : 0, "ssh" : 1, "tcp" :2, "ssl" : 3, "ws" : 4, "wss" : 8}
        if WIN32:
            #on MS Windows, prefer ssh which has a GUI for accepting keys
            #and entering the password:
            order["ssh"] = 0
        def cmp_key(v):
            text = v[-1]    #the text record
            mode = (text or {}).get("mode", "")
            host = v[6]
            host_len = len(host)
            #log("cmp_key(%s) text=%s, mode=%s, host=%s, host_len=%s", v, text, mode, host, host_len)
            #prefer order (from mode), then shorter host string:
            return "%s-%s" % (order.get(mode, mode), host_len)
        srecs = sorted(recs, key=cmp_key)
        has_ws = False
        for rec in srecs:
            uri = self.get_uri(None, *rec)
            uri_menu.append_text(uri)
            d[uri] = rec
            if uri.startswith("ws"):
                has_ws = True
        def connect(*_args):
            uri = uri_menu.get_active_text()
            rec = d[uri]
            password = self.password_entry.get_text()
            uri = self.get_uri(password, *rec)
            self.attach(key, uri)
        uri_menu.set_active(0)
        btn = imagebutton("Connect", icon, clicked_callback=connect)
        def uri_changed(*_args):
            uri = uri_menu.get_active_text()
            ws = uri.startswith("ws")
            bopen.set_sensitive(ws)
            if ws:
                bopen.set_tooltip_text("")
            elif not has_ws:
                bopen.set_tooltip_text("no 'ws' or 'wss' URIs found")
            else:
                bopen.set_tooltip_text("select a 'ws' or 'wss' URI")
        uri_menu.connect("changed", uri_changed)
        uri_changed()
        def browser_open_option(*_args):
            uri = uri_menu.get_active_text()
            rec = d[uri]
            self.browser_open(rec)
        bopen.connect("clicked", browser_open_option)
        return uri_menu, btn, bopen

    def get_platform_icon_name(self, platform):
        for p,i in {
            "win32"     : "win32",
            "darwin"    : "osx",
            "linux"     : "linux",
            "freebsd"   : "freebsd",
            }.items():
            if platform.startswith(p):
                return i
        return None

    def get_pixbuf(self, icon_name):
        icon_filename = os.path.join(get_icon_dir(), icon_name)
        if os.path.exists(icon_filename):
            return GdkPixbuf.Pixbuf.new_from_file(icon_filename)
        return None


def do_main(opts):
    from xpra.platform import program_context
    from xpra.log import enable_color
    with program_context("Xpra-Session-Browser", "Xpra Session Browser"):
        enable_color()
        gui = SessionsGUI(opts)
        register_os_signals(gui.app_signal)
        Gtk.main()
        log("do_main() gui.exit_code=%i", gui.exit_code)
        return gui.exit_code

def main(): # pragma: no cover
    from xpra.scripts.config import make_defaults_struct
    opts = make_defaults_struct()
    return do_main(opts)


if __name__ == "__main__":  # pragma: no cover
    r = main()
    sys.exit(r)
