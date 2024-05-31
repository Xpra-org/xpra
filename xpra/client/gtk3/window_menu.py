# This file is part of Xpra.
# Copyright (C) 2020-2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import gi_import
from xpra.client.gtk3.menu_helper import MenuHelper
from xpra.log import Logger

log = Logger("gtk", "window")

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")


class WindowMenuHelper(MenuHelper):

    def __init__(self, client, window):
        super().__init__(client)
        self.window = window

    def setup_menu(self) -> Gtk.Menu:
        menu = Gtk.Menu()
        # menu.append(self.make_closemenuitem())
        menu.connect("deactivate", self.menu_deactivated)
        # menu.append(self.make_aboutmenuitem())
        menu.append(self.make_infomenuitem())
        # if self.client.client_supports_opengl:
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

    def make_infomenuitem(self) -> Gtk.ImageMenuItem:
        def show_info(*_args) -> None:
            from xpra.client.gtk3.window_info import WindowInfo
            wi = WindowInfo(self.client, self.window)
            wi.show()

        gl = self.menuitem("Window Information", "information.png", "Window state and details", show_info)
        gl.set_tooltip_text()
        return gl

    def make_openglmenuitem(self) -> Gtk.ImageMenuItem:
        gl = self.checkitem("OpenGL")
        gl.set_tooltip_text("hardware accelerated rendering using OpenGL")
        return gl

    def make_minimizemenuitem(self) -> Gtk.ImageMenuItem:
        def minimize(*args) -> None:
            log("minimize%s", args)
            self.window.iconify()

        return self.menuitem("Minimize", "minimize.png", None, minimize)

    def make_maximizemenuitem(self) -> Gtk.ImageMenuItem:
        def maximize(*args) -> None:
            log("maximize%s", args)
            if self.window.is_maximized():
                self.window.unmaximize()
            else:
                self.window.maximize()

        def get_label(maximized) -> str:
            return "Unmaximize" if maximized else "Maximize"

        label = get_label(self.window.is_maximized())
        self.maximize_menuitem = self.menuitem(label, "maximize.png", None, maximize)

        def window_state_updated(widget, event) -> None:
            maximized_changed = event.changed_mask & Gdk.WindowState.MAXIMIZED
            log("state_changed%s maximized_changed=%s", (widget, event), maximized_changed)
            if maximized_changed:
                lbl = get_label(event.new_window_state & Gdk.WindowState.MAXIMIZED)
                self.maximize_menuitem.set_label(lbl)
            self.maximize_menuitem.set_sensitive(self.window.can_maximize())

        self.window.connect("window-state-event", window_state_updated)
        return self.maximize_menuitem

    def make_fullscreenmenuitem(self) -> Gtk.ImageMenuItem:
        def fullscreen(*args) -> None:
            log("fullscreen%s", args)
            self.window.fullscreen()

        return self.menuitem("Fullscreen", "scaling.png", None, fullscreen)

    def make_abovenmenuitem(self) -> Gtk.ImageMenuItem:
        def icon_name() -> str:
            if self.window._above:
                return "ticked.png"
            return "unticked.png"

        def toggle_above(*args) -> None:
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

    def make_refreshmenuitem(self) -> Gtk.ImageMenuItem:
        def force_refresh(*args) -> None:
            log("force refresh%s", args)
            self.client.send_refresh(self.window.wid)
            reset_icon = getattr(self.window, "reset_icon", None)
            if reset_icon:
                reset_icon()

        return self.menuitem("Refresh", "retry.png", None, force_refresh)

    def make_reinitmenuitem(self) -> Gtk.ImageMenuItem:
        def force_reinit(*args) -> None:
            log("force reinit%s", args)
            self.client.reinit_window(self.window.wid, self.window)
            reset_icon = getattr(self.window, "reset_icon", None)
            if reset_icon:
                reset_icon()

        return self.menuitem("Re-initialize", "reinitialize.png", None, force_reinit)

    def make_closemenuitem(self) -> Gtk.ImageMenuItem:
        def close(*args) -> None:
            log("close(%s)", args)
            self.window.close()

        return self.menuitem("Close", "close.png", None, close)
