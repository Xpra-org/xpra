# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.client.gtk_base.gtk_client_base import GTKXpraClient, xor_str
from xpra.gtk_common.gobject_compat import import_gobject3, import_gtk3, import_gdk3
gobject = import_gobject3()
gtk = import_gtk3()
gdk = import_gdk3()
from gi.repository.GdkPixbuf import Pixbuf    #@UnresolvedImport
from gi.repository.GdkPixbuf import InterpType  #@UnresolvedImport

from xpra.client.gtk3.client_window import ClientWindow
from xpra.client.gtk3.tray_menu import GTK3TrayMenu
from xpra.log import Logger
log = Logger()


class XpraClient(GTKXpraClient):

    WINDOW_TOPLEVEL = gtk.WindowType.TOPLEVEL
    INPUT_ONLY = gtk.WindowWindowClass.INPUT_ONLY
    ClientWindowClass = ClientWindow

    def make_hello(self, challenge_response=None):
        capabilities = GTKXpraClient.make_hello(self, challenge_response)
        if xor_str is not None:
            capabilities["encoding.supports_delta"] = [x for x in ("rgb24", "rgb32") if x in self.get_core_encodings()]
        return capabilities

    def client_type(self):
        return "Python/Gtk3"

    def client_toolkit(self):
        return "gtk3"


    def do_get_pixbuf(self, icon_filename):
        return Pixbuf.new_from_file(icon_filename)

    def do_get_image(self, pixbuf, size=None):
        if size>0:
            pixbuf = pixbuf.scale_simple(size, size, InterpType.BILINEAR)
        return  gtk.Image.new_from_pixbuf(pixbuf)


    def make_tray_menu(self):
        return GTK3TrayMenu(self)

    def make_clipboard_helper(self):
        return None

    def get_screen_sizes(self):
        #where has this been moved to? - no docs to tell you :(
        return []

    def get_root_size(self):
        return gdk.get_default_root_window().get_geometry()[2:]

    def set_windows_cursor(self, gtkwindows, new_cursor):
        pass

    def group_leader_for_pid(self, pid, wid):
        return None

    def init_opengl(self, enable_opengl):
        self.opengl_enabled = False
        self.opengl_props = {"info" : "GTK3 does not support OpenGL"}


gobject.type_register(XpraClient)
