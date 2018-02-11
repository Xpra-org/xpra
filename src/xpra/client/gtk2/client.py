# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2015 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject
gobject.threads_init()

from xpra.client.gtk_base.gtk_client_base import GTKXpraClient
from xpra.client.gtk2.tray_menu import GTK2TrayMenu
from xpra.client.gtk2.client_window import ClientWindow
from xpra.log import Logger

log = Logger("gtk", "client")
grablog = Logger("gtk", "client", "grab")



class XpraClient(GTKXpraClient):

    ClientWindowClass = ClientWindow

    def __repr__(self):
        return "gtk2.client"

    def client_type(self):
        return "Python/Gtk2"

    def client_toolkit(self):
        return "gtk2"


    def get_tray_menu_helper_class(self):
        return GTK2TrayMenu


gobject.type_register(XpraClient)
