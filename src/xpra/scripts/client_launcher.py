# This file is part of Parti.
# Copyright (C) 2009 Antoine Martin <antoine@nagafix.co.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

""" client_launcher.py

This is a simple GUI for starting the xpra client.

"""

import pygtk
pygtk.require('2.0')
import gtk
import pango
import socket
from xpra.client import XpraClient

class ApplicationWindow:

    def    __init__(self):
        self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
        self.window.connect("destroy", self.destroy)

        vbox = gtk.VBox(False, 0)
        vbox.set_spacing(15)
        label = gtk.Label("Connect to xpra server")
        label.modify_font(pango.FontDescription("sans 13"))
        vbox.pack_start(label)
        hbox = gtk.HBox(False, 0)
        hbox.set_spacing(5)
        self.host_entry = gtk.Entry(max=64)
        self.host_entry.set_width_chars(16)
        self.host_entry.set_text("127.0.0.1")
        self.port_entry = gtk.Entry(max=5)
        self.port_entry.set_width_chars(5)
        self.port_entry.set_text("16010")
        hbox.pack_start(self.host_entry)
        hbox.pack_start(gtk.Label(":"))
        hbox.pack_start(self.port_entry)
        vbox.pack_start(hbox)
        self.button = gtk.Button("Connect")
        self.button.connect("clicked", self.connect_clicked, None)
        vbox.pack_start(self.button)

        self.window.add(vbox)
        self.window.show_all()
    
    def connect_clicked(self, *args):
        host = self.host_entry.get_text()
        port = self.port_entry.get_text()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, int(port)))
        app = XpraClient(sock, 3, 0, None)
        app.run()

    def destroy(self, *args):
        gtk.main_quit()

if __name__ == "__main__":
    app = ApplicationWindow()
    gtk.main()
