# This file is part of Xpra.
# Copyright (C) 2013, 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.client.gtk_base.gtk_client_base import GTKXpraClient, xor_str

from gi.repository import GObject               #@UnresolvedImport
from gi.repository import Gtk                   #@UnresolvedImport
from gi.repository import Gdk                   #@UnresolvedImport

from xpra.client.gtk3.client_window import ClientWindow
from xpra.client.gtk3.tray_menu import GTK3TrayMenu
from xpra.log import Logger
log = Logger("gtk", "client")


class XpraClient(GTKXpraClient):

    ClientWindowClass = ClientWindow

    def gtk_main(self):
        Gtk.main()

    def make_hello(self):
        capabilities = GTKXpraClient.make_hello(self)
        if xor_str is not None:
            capabilities["encoding.supports_delta"] = [x for x in ("rgb24", "rgb32") if x in self.get_core_encodings()]
        return capabilities

    def client_type(self):
        return "Python/Gtk3"

    def client_toolkit(self):
        return "gtk3"

    def get_notifier_classes(self):
        ncs = GTKXpraClient.get_notifier_classes(self)
        try:
            from xpra.client.gtk3.gtk3_notifier import GTK3_Notifier
            ncs.append(GTK3_Notifier)
        except Exception, e:
            log("cannot load GTK3 notifier: %s", e)
        return ncs


    def get_tray_menu_helper_classes(self):
        tmhc = GTKXpraClient.get_tray_menu_helper_classes(self)
        tmhc.append(GTK3TrayMenu)
        return tmhc

    def make_clipboard_helper(self):
        return None

    def get_screen_sizes(self):
        #where has this been moved to? - no docs to tell you :(
        return []

    def get_root_size(self):
        #this works: ?
        #Gtk.Window().get_screen().get_root_window()
        w, h = Gdk.get_default_root_window().get_geometry()[2:]
        if w<=0 or h<=0 or w>32768 or h>32768:
            log("Gdk returned invalid screen dimensions: %sx%s", w, h)
            w = 2560
            h = 1600
        return w, h

    def set_windows_cursor(self, gtkwindows, new_cursor):
        pass

    def init_opengl(self, enable_opengl):
        self.opengl_enabled = False
        self.opengl_props = {"info" : "GTK3 does not support OpenGL"}


GObject.type_register(XpraClient)
