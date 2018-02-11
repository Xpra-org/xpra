# This file is part of Xpra.
# Copyright (C) 2013-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.client.gtk_base.gtk_client_base import GTKXpraClient

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
        try:
            from xpra.client.gtk3.gtk3_notifier import GTK3_Notifier
            ncs.append(GTK3_Notifier)
        except Exception as e:
            log.warn("Warning: failed to load the GTK3 notification class")
            log.warn(" %s", e)
        return ncs

    def do_get_core_encodings(self):
        cencs = GTKXpraClient.do_get_core_encodings(self)
        #we can now paint with alpha via pixbufs:
        cencs.append("rgb32")
        return cencs

    def get_xdpi(self):
        xdpi = GTKXpraClient.get_xdpi(self)
        if xdpi>0:
            return xdpi
        return Gdk.Screen.get_default().get_resolution()

    def get_ydpi(self):
        ydpi = GTKXpraClient.get_ydpi(self)
        if ydpi>0:
            return ydpi
        return Gdk.Screen.get_default().get_resolution()


    def get_tray_menu_helper_classes(self):
        tmhc = GTKXpraClient.get_tray_menu_helper_classes(self)
        tmhc.append(GTK3TrayMenu)
        return tmhc


    def get_mouse_position(self):
        #with GTK3, we can get None values!
        p = self.get_root_window().get_pointer()[-3:-1]
        return self.sp(p[0] or 0, p[1] or 0)


GObject.type_register(XpraClient)
