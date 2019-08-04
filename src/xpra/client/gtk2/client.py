# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2015 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pylint: disable=wrong-import-position

import gobject  #@UnresolvedImport
gobject.threads_init()

from xpra.client.gtk_base.gtk_client_base import GTKXpraClient
from xpra.client.gtk2.client_window import ClientWindow


class XpraClient(GTKXpraClient):

    ClientWindowClass = ClientWindow

    def __repr__(self):
        return "gtk2.client"

    def client_type(self):
        return "Python/GTK2"

    def client_toolkit(self):
        return "GTK2"


    def get_tray_menu_helper_class(self):
        from xpra.client.gtk2.tray_menu import GTK2TrayMenu
        return GTK2TrayMenu


gobject.type_register(XpraClient)
