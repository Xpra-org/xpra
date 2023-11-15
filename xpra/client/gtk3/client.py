# This file is part of Xpra.
# Copyright (C) 2013-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from gi.repository import GObject, Gdk               #@UnresolvedImport

from xpra.os_util import OSX, POSIX, is_Wayland
from xpra.client.gtk3.gtk_client_base import GTKXpraClient
from xpra.client.gtk3.client_window import ClientWindow
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

        def nwarn(notifier_name: str, e: Exception):
            from xpra.log import Logger
            log = Logger("gtk", "client")
            log("get_notifier_classes()", exc_info=True)
            log.warn(f"Warning: failed to load the {notifier_name} notifier")
            log.warn(f" {e}")

        if not OSX:
            # pylint: disable=import-outside-toplevel
            try:
                from xpra.client.gtk3.gtk3_notifier import GTK3_Notifier
                ncs.append(GTK3_Notifier)
            except Exception as e:
                nwarn("GObject", e)
        try:
            from xpra.gtk_common.gtk_notifier import GTK_Notifier
            ncs.append(GTK_Notifier)
        except Exception as e:
            nwarn("GTK", e)
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
        from xpra.client.gtk3.tray_menu import GTK3TrayMenu
        return GTK3TrayMenu


    def get_mouse_position(self):
        #with GTK3, we can get None values!
        root = self.get_root_window()
        if not root:
            return -1, -1
        p = root.get_pointer()[-3:-1]
        return self.sp(p[0] or 0, p[1] or 0)


GObject.type_register(XpraClient)
