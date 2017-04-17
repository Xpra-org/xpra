# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import pango
import os.path
import subprocess
from collections import OrderedDict

from xpra.gtk_common.gobject_compat import import_gtk, import_gdk, import_glib
gtk = import_gtk()
gdk = import_gdk()
glib = import_glib()
glib.threads_init()

from xpra.platform.paths import get_icon_dir, get_xpra_command
from xpra.child_reaper import getChildReaper
from xpra.exit_codes import EXIT_STR
from xpra.gtk_common.gtk_util import gtk_main, add_close_accel, pixbuf_new_from_file, TableBuilder, scaled_image, color_parse, imagebutton, STATE_NORMAL
from xpra.log import Logger
log = Logger("mdns", "util")


class mdns_sessions(gtk.Window):

    def __init__(self):
        gtk.Window.__init__(self)
        self.set_title("mDNS Sessions")
        self.set_border_width(20)
        self.set_resizable(True)
        self.set_decorated(True)
        icon = self.get_pixbuf("xpra")
        if icon:
            self.set_icon(icon)
        add_close_accel(self, self.quit)
        self.connect("delete_event", self.quit)

        self.child_reaper = getChildReaper()

        self.vbox = gtk.VBox(False, 20)
        self.add(self.vbox)

        title = gtk.Label("Xpra mDNS Sessions")
        title.modify_font(pango.FontDescription("sans 14"))
        self.vbox.add(title)

        self.warning = gtk.Label(" ")
        red = color_parse("red")
        self.warning.modify_fg(STATE_NORMAL, red)
        self.vbox.add(self.warning)

        hbox = gtk.HBox(False, 10)
        al = gtk.Alignment(xalign=1, yalign=0.5)
        al.add(gtk.Label("Password:"))
        hbox.add(al)
        self.password_entry = gtk.Entry(max=128)
        self.password_entry.set_width_chars(16)
        self.password_entry.set_visibility(False)
        al = gtk.Alignment(xalign=0, yalign=0.5)
        al.add(self.password_entry)
        hbox.add(al)
        self.vbox.add(hbox)

        self.table = None
        self.records = []
        self.populate_table()
        #self.set_size_request(0, 200)
        from xpra.net.mdns import XPRA_MDNS_TYPE, get_listener_class
        listener = get_listener_class()
        self.listener = listener(XPRA_MDNS_TYPE, mdns_found=None, mdns_add=self.mdns_add, mdns_remove=self.mdns_remove)
        log("%s%s=%s", listener, (XPRA_MDNS_TYPE, None, self.mdns_add, self.mdns_remove), self.listener)
        self.listener.start()
        self.show_all()

    def quit(self, *args):
        log("quit%s", args)
        self.do_quit()

    def do_quit(self):
        log("do_quit()")
        gtk.main_quit()

    def mdns_remove(self, r_interface, r_protocol, r_name, r_stype, r_domain, r_flags):
        log("mdns_remove%s", (r_interface, r_protocol, r_name, r_stype, r_domain, r_flags))
        old_recs = self.records
        self.records = [(interface, protocol, name, stype, domain, host, address, port, text) for
                        (interface, protocol, name, stype, domain, host, address, port, text) in self.records
                        if (interface!=r_interface or protocol!=r_protocol or name!=r_name or stype!=r_stype or domain!=r_domain)]
        if old_recs!=self.records:
            glib.idle_add(self.populate_table)

    def mdns_add(self, interface, protocol, name, stype, domain, host, address, port, text):
        log("mdns_add%s", (interface, protocol, name, stype, domain, host, address, port, text))
        text = text or {}
        self.records.append((interface, protocol, name, stype, domain, host, address, port, text))
        glib.idle_add(self.populate_table)

    def populate_table(self):
        log("populate_table: %i records", len(self.records))
        if self.table:
            self.vbox.remove(self.table)
            self.table = None
        if not self.records:
            self.table = gtk.Label("No sessions found")
            self.vbox.add(self.table)
            self.table.show()
            return
        tb = TableBuilder(1, 6, False)
        tb.add_row(gtk.Label("Host"), gtk.Label("Session"), gtk.Label("Platform"), gtk.Label("Type"), gtk.Label("URI"), gtk.Label("Connect"))
        self.table = tb.get_table()
        self.vbox.add(self.table)
        self.table.resize(1+len(self.records), 5)
        #group them by uuid
        d = OrderedDict()
        for i, (interface, protocol, name, stype, domain, host, address, port, text) in enumerate(self.records):
            uuid = text.get("uuid", "")
            display = text.get("display", "")
            platform = text.get("platform", "")
            dtype = text.get("type", "")
            key = (uuid, uuid or i, host, display, platform, dtype)
            d.setdefault(key, []).append((interface, protocol, name, stype, domain, host, address, port, text))
        for key, recs in d.items():
            uuid, _, host, display, platform, dtype = key
            title = uuid
            if display:
                title = display
            label = gtk.Label(title)
            if uuid!=title:
                label.set_tooltip_text(uuid)
            #try to use an icon for the platform:
            platform_icon_name = self.get_platform_icon_name(platform)
            if platform_icon_name:
                pwidget = scaled_image(self.get_pixbuf("%s.png" % platform_icon_name), 24)
                pwidget.set_tooltip_text(platform)
            else:
                pwidget = gtk.Label(platform)
            w, c = self.make_connect_widgets(recs, address, port, display)
            tb.add_row(gtk.Label(host), label, pwidget, gtk.Label(dtype), w, c)
        self.table.show_all()

    def get_uri(self, password, interface, protocol, name, stype, domain, host, address, port, text):
        dstr = ""
        display = text.get("display", "")
        username = text.get("username", "")
        mode = text.get("mode", "")
        if display.startswith(":"):
            dstr = display[1:]
        if username:
            if password:
                uri = "%s/%s:%s@%s:%s/%s" % (mode, username, password, address, port, dstr)
            else:
                uri = "%s/%s@%s:%s/%s" % (mode, username, address, port, dstr)
        else:
            uri = "%s/%s:%s/%s" % (mode, address, port, dstr)
        return uri

    def attach(self, uri):
        self.warning.set_text("")
        cmd = get_xpra_command() + ["attach", uri]
        proc = subprocess.Popen(cmd)
        log("attach() Popen(%s)=%s", cmd, proc)
        def proc_exit(*args):
            log("proc_exit%s", args)
            c = proc.poll()
            if c not in (0, None):
                self.warning.set_text(EXIT_STR.get(c, "exit code %s" % c).replace("_", " "))
        self.child_reaper.add_process(proc, "client-%s" % uri, cmd, True, True, proc_exit)

    def make_connect_widgets(self, recs, address, port, display):
        icon = self.get_pixbuf("connect.png")
        if len(recs)==1:
            #single record, single uri:
            uri = self.get_uri(None, *recs[0])
            def clicked(*args):
                password = self.password_entry.get_text()
                uri = self.get_uri(password, *recs[0])
                self.attach(uri)
            btn = imagebutton("Connect", icon, clicked_callback=clicked)
            return gtk.Label(uri), btn
        #multiple modes / uris
        uri_menu = gtk.combo_box_new_text()
        d = {}
        for rec in sorted(recs):
            uri = self.get_uri(None, *rec)
            uri_menu.append_text(uri)
            d[uri] = rec
        def connect(*args):
            uri = uri_menu.get_active_text()
            rec = d[uri]
            password = self.password_entry.get_text()
            uri = self.get_uri(password, *rec)
            self.attach(uri)
        uri_menu.set_active(0)
        btn = imagebutton("Connect", icon, clicked_callback=connect)
        #btn = gtk.Button(">")
        #btn.connect("clicked", connect)
        return uri_menu, btn

    def get_platform_icon_name(self, platform):
        for p,i in {
                    "win32"     : "win32",
                    "darwin"    : "osx",
                    "linux2"    : "linux",
                    "freebsd"   : "freebsd",
                    }.items():
            if platform.startswith(p):
                return i
        return None

    def get_pixbuf(self, icon_name):
        icon_filename = os.path.join(get_icon_dir(), icon_name)
        if os.path.exists(icon_filename):
            return pixbuf_new_from_file(icon_filename)
        return None


def main():
    from xpra.platform import program_context
    from xpra.log import enable_color
    with program_context("Xpra-Browser", "Xpra Session Browser"):
        enable_color()
        return do_main()

def do_main():
    mdns_sessions()
    gtk_main()


if __name__ == "__main__":
    main()
