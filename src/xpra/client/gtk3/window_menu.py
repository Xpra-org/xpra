# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from gi.repository import Gtk

from xpra.client.gtk_base.menu_helper import MenuHelper
from xpra.log import Logger

log = Logger("gtk", "window")


class WindowMenuHelper(MenuHelper):

    def __init__(self, client, window):
        super().__init__(client)
        self.window = window

    def setup_menu(self):
        menu = Gtk.Menu()
        menu.append(self.make_closemenuitem())
        menu.connect("deactivate", self.menu_deactivated)
        menu.append(self.make_aboutmenuitem())
        if self.client.client_supports_opengl:
            menu.append(self.make_openglmenuitem())
        menu.append(self.make_refreshmenuitem())
        menu.append(self.make_reinitmenuitem())
        menu.show_all()
        return menu

    def make_openglmenuitem(self):
        gl = self.checkitem("OpenGL")
        gl.set_tooltip_text("hardware accelerated rendering using OpenGL")
        return gl


    def make_refreshmenuitem(self):
        def force_refresh(*_args):
            log("force refresh")
            self.client.send_refresh(self.window._id)
            reset_icon = getattr(self.window, "reset_icon", None)
            if reset_icon:
                reset_icon()
        return self.handshake_menuitem("Refresh", "retry.png", None, force_refresh)

    def make_reinitmenuitem(self):
        def force_reinit(*_args):
            log("force reinit")
            self.client.reinit_window(self.window._id, self.window)
            reset_icon = getattr(self.window, "reset_icon", None)
            if reset_icon:
                reset_icon()
        return self.handshake_menuitem("Re-initialize", "reinitialize.png", None, force_reinit)
