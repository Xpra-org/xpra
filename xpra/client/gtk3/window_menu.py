# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from gi.repository import Gtk, Gdk

from xpra.client.gtk_base.menu_helper import MenuHelper
from xpra.log import Logger

log = Logger("gtk", "window")


class WindowMenuHelper(MenuHelper):

    def __init__(self, client, window):
        super().__init__(client)
        self.window = window

    def setup_menu(self):
        menu = Gtk.Menu()
        #menu.append(self.make_closemenuitem())
        menu.connect("deactivate", self.menu_deactivated)
        #menu.append(self.make_aboutmenuitem())
        menu.append(self.make_infomenuitem())
        #if self.client.client_supports_opengl:
        #    menu.append(self.make_openglmenuitem())
        menu.append(self.make_minimizemenuitem())
        menu.append(self.make_maximizemenuitem())
        menu.append(self.make_fullscreenmenuitem())
        menu.append(self.make_abovenmenuitem())
        menu.append(self.make_refreshmenuitem())
        menu.append(self.make_reinitmenuitem())
        menu.append(self.make_closemenuitem())
        menu.show_all()
        return menu

    def make_infomenuitem(self):
        def show_info(*_args):
            from xpra.client.gtk_base.window_info import WindowInfo
            wi = WindowInfo(self.client, self.window)
            wi.show()
        gl = self.menuitem("Window Information", "information.png", "Window state and details", show_info)
        gl.set_tooltip_text()
        return gl

    def make_openglmenuitem(self):
        gl = self.checkitem("OpenGL")
        gl.set_tooltip_text("hardware accelerated rendering using OpenGL")
        return gl

    def make_minimizemenuitem(self):
        def minimize(*args):
            log("minimize%s", args)
            self.window.iconify()
        return self.menuitem("Minimize", "minimize.png", None, minimize)

    def make_maximizemenuitem(self):
        def maximize(*args):
            log("maximize%s", args)
            if self.window.is_maximized():
                self.window.unmaximize()
            else:
                self.window.maximize()
        def get_label(maximized):
            return "Unmaximize" if maximized else "Maximize"
        label = get_label(self.window.is_maximized())
        self.maximize_menuitem = self.menuitem(label, "maximize.png", None, maximize)
        def set_sensitive_state():
            self.maximize_menuitem.set_sensitive(self.window.can_maximize())
        def window_state_updated(widget, event):
            maximized_changed = event.changed_mask & Gdk.WindowState.MAXIMIZED
            log("state_changed%s maximized_changed=%s", (widget, event), maximized_changed)
            if maximized_changed:
                label = get_label(event.new_window_state & Gdk.WindowState.MAXIMIZED)
                self.maximize_menuitem.set_label(label)
        self.window.connect("window-state-event", window_state_updated)
        return self.maximize_menuitem

    def make_fullscreenmenuitem(self):
        def fullscreen(*args):
            log("fullscreen%s", args)
            self.window.fullscreen()
        return self.menuitem("Fullscreen", "scaling.png", None, fullscreen)

    def make_abovenmenuitem(self):
        def icon_name():
            if self.window._above:
                return "ticked.png"
            return "unticked.png"
        def toggle_above(*args):
            above = not self.window._above
            log("toggle_above%s above=%s", args, above)
            self.window._above = above
            self.window.set_keep_above(above)
            from xpra.platform.gui import get_icon_size
            icon_size = self.menu_icon_size or get_icon_size()
            image = self.get_image(icon_name(), icon_size)
            self.above_menuitem.set_image(image)
        self.above_menuitem = self.menuitem("Always on top", icon_name(), None, toggle_above)
        return self.above_menuitem


    def make_refreshmenuitem(self):
        def force_refresh(*args):
            log("force refresh%s", args)
            self.client.send_refresh(self.window._id)
            reset_icon = getattr(self.window, "reset_icon", None)
            if reset_icon:
                reset_icon()
        return self.menuitem("Refresh", "retry.png", None, force_refresh)

    def make_reinitmenuitem(self):
        def force_reinit(*args):
            log("force reinit%s", args)
            self.client.reinit_window(self.window._id, self.window)
            reset_icon = getattr(self.window, "reset_icon", None)
            if reset_icon:
                reset_icon()
        return self.menuitem("Re-initialize", "reinitialize.png", None, force_reinit)

    def make_closemenuitem(self):
        def close(*args):
            log("close(%s)", args)
            self.window.close()
        return self.menuitem("Close", "close.png", None, close)
