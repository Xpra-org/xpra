# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.gtk_common.gobject_compat import import_gtk, import_gdk, import_glib
gtk = import_gtk()
gdk = import_gdk()
glib = import_glib()
import os.path
from xpra.platform.paths import get_icon_dir
from xpra.gtk_common.gtk_util import gtk_main, add_close_accel, pixbuf_new_from_file, TableBuilder, scaled_image
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

        self.vbox = gtk.VBox(False, 20)
        self.add(self.vbox)

        title = gtk.Label("Xpra Sessions")
        self.vbox.add(title)

        self.table = None
        self.records = []
        self.populate_table()
        #self.set_size_request(0, 200)
        from xpra.net.mdns import XPRA_MDNS_TYPE
        from xpra.net.mdns.avahi_listener import AvahiListener
        self.listener = AvahiListener(XPRA_MDNS_TYPE, mdns_found=None, mdns_add=self.mdns_add, mdns_remove=self.mdns_remove)
        self.listener.start()
        self.show_all()

    def quit(self, *args):
        log("quit%s", args)
        gtk.main_quit()

    def mdns_remove(self, r_interface, r_protocol, r_name, r_stype, r_domain, r_flags):
        log.info("mdns_remove%s", (r_interface, r_protocol, r_name, r_stype, r_domain, r_flags))
        old_recs = self.records
        self.records = [(interface, protocol, name, stype, domain, host, address, port, text) for
                        (interface, protocol, name, stype, domain, host, address, port, text) in self.records
                        if (interface!=r_interface or protocol!=r_protocol or name!=r_name or stype!=r_stype or domain!=r_domain)]
        if old_recs!=self.records:
            glib.idle_add(self.populate_table)

    def mdns_add(self, interface, protocol, name, stype, domain, host, address, port, text):
        log.info("mdns_add%s", (interface, protocol, name, stype, domain, host, address, port, text))
        text = text or {}
        self.records.append((interface, protocol, name, stype, domain, host, address, port, text))
        glib.idle_add(self.populate_table)

    def populate_table(self):
        log.info("populate_table: %i records", len(self.records))
        if self.table:
            self.vbox.remove(self.table)
            self.table = None
        tb = TableBuilder(1, 5, False)
        tb.add_row(gtk.Label("Session"), gtk.Label("Host"), gtk.Label("Platform"), gtk.Label("Type"), gtk.Label("Connect"))
        self.table = tb.get_table()
        self.vbox.add(self.table)
        self.table.resize(1+len(self.records), 5)
        #for interface, protocol, name, stype, domain, host, address, port, text in self.records:
        for _, _, _, stype, _, host, address, port, text in self.records:
            uuid = text.get("uuid", "")
            display = text.get("display")
            username = text.get("username")
            title = uuid
            if display:
                title = display
            label = gtk.Label(title)
            if uuid!=title:
                label.set_tooltip_text(uuid)
            platform = text.get("platform", "")
            stype = text.get("type", "")
            mode = text.get("mode", "")
            dstr = ""
            if display.startswith(":"):
                dstr = display[1:]
            if username:
                uri = "%s/%s@%s:%s/%s" % (mode, username, address, port, dstr)
            else:
                uri = "%s/%s:%s/%s" % (mode, address, port, dstr)
            #try to use an icon for the platform:
            platform_icon_name = self.get_platform_icon_name(platform)
            if platform_icon_name:
                pwidget = scaled_image(self.get_pixbuf("%s.png" % platform_icon_name), 24)
                pwidget.set_tooltip_text(platform)
            else:
                pwidget = gtk.Label(platform)
            def connect(*args):
                from xpra.platform.paths import get_xpra_command
                import subprocess
                cmd = get_xpra_command() + ["attach", uri]
                subprocess.Popen(cmd)
            btn = gtk.Button(uri)
            btn.connect("clicked", connect)
            tb.add_row(label, gtk.Label(host), pwidget, gtk.Label(stype), btn)
        self.table.show_all()

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

    def bool_icon(self, image, on_off):
        if on_off:
            icon = self.get_pixbuf("ticked-small.png")
        else:
            icon = self.get_pixbuf("unticked-small.png")
        image.set_from_pixbuf(icon)


def main():
    mdns_sessions()
    gtk_main()


if __name__ == "__main__":
    main()
