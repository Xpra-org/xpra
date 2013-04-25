# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.client.gtk_client_base import GTKXpraClient
from wimpiggy.gobject_compat import import_gobject3, import_gtk3, import_gdk3
gobject = import_gobject3()
gtk = import_gtk3()
gdk = import_gdk3()

from wimpiggy.log import Logger
log = Logger()


class XpraClient(GTKXpraClient):

    def __init__(self, conn, opts):
        GTKXpraClient.__init__(self, conn, opts)

    def get_root_size(self):
        return gdk.get_default_root_window().get_geometry()[2:]

    def set_windows_cursor(self, gtkwindows, new_cursor):
        pass


gobject.type_register(XpraClient)
