# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.client.gtk_base.gtk_client_base import GTKXpraClient
from xpra.gobject_compat import import_gobject3, import_gtk3, import_gdk3
gobject = import_gobject3()
gtk = import_gtk3()
gdk = import_gdk3()

from xpra.scripts.config import ENCODINGS
from xpra.client.gtk3.client_window import ClientWindow
from xpra.log import Logger
log = Logger()


class XpraClient(GTKXpraClient):

    WINDOW_TOPLEVEL = gtk.WindowType.TOPLEVEL
    INPUT_ONLY = gtk.WindowWindowClass.INPUT_ONLY

    def __init__(self, conn, opts):
        GTKXpraClient.__init__(self, conn, opts)

    def make_hello(self, challenge_response=None):
        capabilities = GTKXpraClient.make_hello(self, challenge_response)
        capabilities["encoding.supports_delta"] = [x for x in ("rgb24",) if x in ENCODINGS]
        return capabilities

    def client_type(self):
        return "Python/Gtk3"

    def get_screen_sizes(self):
        #where has this been moved to? - no docs to tell you :(
        return []

    def get_root_size(self):
        return gdk.get_default_root_window().get_geometry()[2:]

    def set_windows_cursor(self, gtkwindows, new_cursor):
        pass

    def group_leader_for_pid(self, pid, wid):
        return None

    def get_client_window_class(self, metadata):
        return ClientWindow

    def init_opengl(self, enable_opengl):
        self.opengl_enabled = False
        self.opengl_props = {"info" : "GTK3 does not support OpenGL"}


gobject.type_register(XpraClient)
