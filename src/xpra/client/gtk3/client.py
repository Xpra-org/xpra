# This file is part of Xpra.
# Copyright (C) 2013-2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.client.gtk_base.gtk_client_base import GTKXpraClient

import sys
from gi.repository import GObject               #@UnresolvedImport
from gi.repository import Gtk                   #@UnresolvedImport

#this is an entry point, so do thread init early:
#GObject.threads_init()
#Gdk.threads_init()

from xpra.client.gtk3.client_window import ClientWindow
from xpra.client.gtk3.tray_menu import GTK3TrayMenu
from xpra.log import Logger
log = Logger("gtk", "client")

WIN32 = sys.platform.startswith("win")


class XpraClient(GTKXpraClient):

    ClientWindowClass = ClientWindow

    def gtk_main(self):
        Gtk.main()

    def make_hello(self):
        #see http://xpra.org/trac/ticket/640#comment:43
        log.error("this client is fundamentally broken - do not use")
        capabilities = GTKXpraClient.make_hello(self)
        capabilities["encoding.supports_delta"] = [x for x in ("rgb24", "rgb32") if x in self.get_core_encodings()]
        return capabilities

    def __repr__(self):
        return "gtk3.client"

    def client_type(self):
        return "Python/Gtk3"

    def client_toolkit(self):
        return "gtk3"

    def get_notifier_classes(self):
        ncs = GTKXpraClient.get_notifier_classes(self)
        if not WIN32:
            #for some reason, not included in win32 builds?
            try:
                from xpra.client.gtk3.gtk3_notifier import GTK3_Notifier
                ncs.append(GTK3_Notifier)
            except Exception as e:
                log("failed to load the GTK3 notification class: %s", e)
        return ncs

    def do_get_core_encodings(self):
        cencs = GTKXpraClient.do_get_core_encodings(self)
        for x in ("webp", ):
            if x in cencs:
                cencs.remove(x)
        #for some reason, the cairo_workaround does not work for ARGB32
        #cencs.append("rgb32")
        return cencs


    def get_tray_menu_helper_classes(self):
        tmhc = GTKXpraClient.get_tray_menu_helper_classes(self)
        tmhc.append(GTK3TrayMenu)
        return tmhc

    def make_clipboard_helper(self):
        return None

    def set_windows_cursor(self, windows, cursor_data):
        #avoid buggy win32 version:
        if not sys.platform.startswith("win"):
            GTKXpraClient.set_windows_cursor(self, windows, cursor_data)

    def get_mouse_position(self):
        #with GTK3, we can get None values!
        p = self.get_root_window().get_pointer()
        return self.sp(p[0] or 0, p[1] or 0)


GObject.type_register(XpraClient)
