# This file is part of Xpra.
# Copyright (C) 2013-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

import gi
gi.require_version("Gtk", "3.0")  # @UndefinedVariable
gi.require_version("Gdk", "3.0")  # @UndefinedVariable
from gi.repository import GObject, Gdk               #@UnresolvedImport

from xpra.os_util import OSX, POSIX, is_Wayland
from xpra.client.gtk3.client_base import GTKXpraClient
from xpra.client.gtk3.window import ClientWindow
from xpra.platform.gui import get_xdpi, get_ydpi

class XpraClient(GTKXpraClient):

    ClientWindowClass = ClientWindow

    def __repr__(self):  #pylint: disable=arguments-differ
        return "gtk3.client"

    def client_type(self) -> str:
        return "Python/GTK3"

    def client_toolkit(self) -> str:
        if POSIX and not OSX:
            backend = os.environ.get("GDK_BACKEND", "")
            if not backend and is_Wayland():
                backend = "Wayland"
            if backend:
                #capitalize, ie: "x11" -> "X11"
                backend = backend[0].upper()+backend[1:]
                return f"GTK3 {backend}"
        return "GTK3"


    def get_notifier_classes(self):
        ncs = super().get_notifier_classes()
        if not OSX:
            # pylint: disable=import-outside-toplevel
            try:
                from xpra.client.gtk3.notifier import GINotifier
                ncs.append(GINotifier)
            except Exception as e:
                from xpra.log import Logger
                log = Logger("gtk", "client")
                log.warn("Warning: failed to load the GTK3 notification class")
                log.warn(" %s", e)
        return ncs

    def get_screen_resolution(self) -> int:
        screen = Gdk.Screen.get_default()
        if not screen:
            #wayland?
            return -1
        return round(screen.get_resolution())

    def get_xdpi(self) -> int:
        xdpi = get_xdpi()
        if xdpi>0:
            return xdpi
        return round(self.get_screen_resolution())

    def get_ydpi(self) -> int:
        ydpi = get_ydpi()
        if ydpi>0:
            return ydpi
        return round(self.get_screen_resolution())


    def get_tray_menu_helper_class(self):
        # pylint: disable=import-outside-toplevel
        from xpra.client.gtk3.tray_menu import GTKTrayMenu
        return GTKTrayMenu


    def get_mouse_position(self):
        #with GTK3, we can get None values!
        root = self.get_root_window()
        if not root:
            return -1, -1
        p = root.get_pointer()[-3:-1]
        return self.sp(p[0] or 0, p[1] or 0)


GObject.type_register(XpraClient)
